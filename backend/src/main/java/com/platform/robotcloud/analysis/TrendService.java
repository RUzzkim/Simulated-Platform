package com.platform.robotcloud.analysis;

import com.platform.robotcloud.telemetry.TelemetryData;
import com.platform.robotcloud.telemetry.TelemetryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 趋势 / 预测性维护：对窗口内每关节的 effort 等时间分桶取均值，线性回归求斜率，
 * 再用异常检测给出的「基线上界」当危险线，外推「照这个趋势多久到上界」。
 *
 * <p>只做 effort：它最能反映负载/磨损；velocity/position 的均值趋势对预测性维护意义不大。
 * 危险线复用 {@link AnomalyService} 的 mean+kσ 上界，和异常检测口径一致，不另立一套阈值。
 */
@Service
public class TrendService {

    private static final Logger log = LoggerFactory.getLogger(TrendService.class);

    /** 与异常检测/历史曲线同量级的扫描上限，防止大窗口拉满内存。 */
    private static final int MAX_RAW_SCAN = 20000;
    /** 分桶数上下限：太少回归没意义，太多每桶样本不足。 */
    private static final int MIN_BUCKETS = 4;
    private static final int MAX_BUCKETS = 100;
    private static final int DEFAULT_BUCKETS = 12;
    /** 样本太少时趋势没有统计意义，标 insufficient（仍返回，调用方应弱化处理）。 */
    private static final int MIN_SAMPLES = 30;
    /** 斜率绝对值低于此视为「基本平稳」，不外推预警（避免噪声放大成假趋势）。 */
    private static final double FLAT_SLOPE = 1e-6;
    /** 只对 effort 做趋势。 */
    private static final String METRIC = "effort";
    /** 基线上界用的 σ 倍数，与异常检测默认一致。 */
    private static final double SIGMA = 3.0;

    private final TelemetryRepository repository;
    private final AnomalyService anomalyService;

    public TrendService(TelemetryRepository repository, AnomalyService anomalyService) {
        this.repository = repository;
        this.anomalyService = anomalyService;
    }

    public TrendReport analyze(Long deviceId, LocalDateTime from, LocalDateTime to, int buckets) {
        int b = clampBuckets(buckets);
        List<TelemetryData> raw = repository.findSeries(deviceId, from, to, PageRequest.of(0, MAX_RAW_SCAN));
        int frames = raw.size();
        if (frames == 0) {
            return new TrendReport(deviceId, from, to, METRIC, b, 0, false, List.of());
        }

        // 基线上界（每关节 effort 的 mean+kσ），直接复用异常检测，避免重复实现统计。
        AnomalyReport baseline = anomalyService.detect(deviceId, from, to, SIGMA);
        Map<String, double[]> effortBaseline = new LinkedHashMap<>(); // joint -> [mean, upper]
        for (AnomalyReport.JointBaseline jb : baseline.baselines()) {
            if (METRIC.equals(jb.metric())) {
                effortBaseline.put(jb.joint(), new double[]{jb.mean(), jb.upper()});
            }
        }

        // 分桶：按时间等分成 b 段，每段累计 effort 均值。
        long spanSec = Math.max(1, Duration.between(from, to).getSeconds());
        double bucketSec = (double) spanSec / b;
        Map<String, JointMetrics.Accumulator[]> perJoint = new LinkedHashMap<>();
        for (TelemetryData frame : raw) {
            long offset = Math.max(0, Duration.between(from, frame.getReportedAt()).getSeconds());
            int idx = (int) Math.min(b - 1, (long) (offset / bucketSec));
            JointMetrics.forEach(frame, (joint, metric, value) -> {
                if (!METRIC.equals(metric)) {
                    return;
                }
                JointMetrics.Accumulator[] arr = perJoint.computeIfAbsent(joint, key -> {
                    JointMetrics.Accumulator[] a = new JointMetrics.Accumulator[b];
                    for (int i = 0; i < b; i++) {
                        a[i] = new JointMetrics.Accumulator();
                    }
                    return a;
                });
                arr[idx].add(value);
            });
        }

        List<TrendReport.JointTrend> trends = new ArrayList<>(perJoint.size());
        for (Map.Entry<String, JointMetrics.Accumulator[]> entry : perJoint.entrySet()) {
            String joint = entry.getKey();
            JointMetrics.Accumulator[] arr = entry.getValue();

            // 收集非空桶的 (中点小时, 均值)，画折线也用它
            List<TrendReport.Bucket> sampleBuckets = new ArrayList<>();
            List<double[]> xy = new ArrayList<>(); // [hoursFromStart, mean]
            for (int i = 0; i < b; i++) {
                if (arr[i].count() == 0) {
                    continue;
                }
                double midSec = (i + 0.5) * bucketSec;
                LocalDateTime at = from.plusSeconds((long) midSec);
                double mean = arr[i].mean();
                sampleBuckets.add(new TrendReport.Bucket(at, JointMetrics.round(mean), arr[i].count()));
                xy.add(new double[]{midSec / 3600.0, mean});
            }
            if (xy.isEmpty()) {
                continue;
            }

            double slopePerHour = leastSquaresSlope(xy);
            double current = xy.get(xy.size() - 1)[1]; // 最近一个非空桶的均值
            double[] base = effortBaseline.get(joint);
            double mean = base != null ? base[0] : averageY(xy);
            double upper = base != null ? base[1] : mean;

            Double hoursToUpper = null;
            String projection;
            if (current >= upper && upper > 0) {
                projection = "当前 effort 已达到或超过基线上界，建议立即检查";
            } else if (slopePerHour <= FLAT_SLOPE) {
                projection = "趋势平稳或下降，暂无预警";
            } else {
                double h = (upper - current) / slopePerHour;
                if (h > 0) {
                    hoursToUpper = JointMetrics.round(h);
                    projection = String.format("按当前趋势约 %.1f 小时后 effort 触及基线上界", h);
                } else {
                    projection = "趋势平稳，暂无预警";
                }
            }

            trends.add(new TrendReport.JointTrend(
                    joint, METRIC,
                    JointMetrics.round(slopePerHour),
                    JointMetrics.round(current),
                    JointMetrics.round(mean),
                    JointMetrics.round(upper),
                    hoursToUpper,
                    projection,
                    sampleBuckets));
        }
        trends.sort((a, c) -> Double.compare(c.slopePerHour(), a.slopePerHour())); // 上升最快的排前面

        boolean sufficient = frames >= MIN_SAMPLES;
        log.debug("device {} trend: {} frames, {} joints, {} buckets", deviceId, frames, trends.size(), b);
        return new TrendReport(deviceId, from, to, METRIC, b, frames, sufficient, trends);
    }

    /** 最小二乘求斜率：slope = Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)。点数<2 或 x 无变化时返回 0。 */
    private static double leastSquaresSlope(List<double[]> xy) {
        int n = xy.size();
        if (n < 2) {
            return 0;
        }
        double sumX = 0;
        double sumY = 0;
        for (double[] p : xy) {
            sumX += p[0];
            sumY += p[1];
        }
        double meanX = sumX / n;
        double meanY = sumY / n;
        double num = 0;
        double den = 0;
        for (double[] p : xy) {
            double dx = p[0] - meanX;
            num += dx * (p[1] - meanY);
            den += dx * dx;
        }
        return den == 0 ? 0 : num / den;
    }

    private static double averageY(List<double[]> xy) {
        double sum = 0;
        for (double[] p : xy) {
            sum += p[1];
        }
        return xy.isEmpty() ? 0 : sum / xy.size();
    }

    private int clampBuckets(int buckets) {
        if (buckets <= 0) {
            return DEFAULT_BUCKETS;
        }
        return Math.max(MIN_BUCKETS, Math.min(MAX_BUCKETS, buckets));
    }
}
