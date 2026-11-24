package com.platform.robotcloud.analysis;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.platform.robotcloud.telemetry.TelemetryData;
import com.platform.robotcloud.telemetry.TelemetryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 遥测异常检测：对窗口内每个关节的 effort / velocity 建立自适应基线（均值 ± kσ），
 * 再回扫每一帧把越界的样本标成异常点。纯统计、无外部依赖，跑在已有 telemetry_data 上。
 *
 * <p>为什么用「设备自身近期基线」而不是固定阈值：不同工位、不同负载的正常区间差很多，
 * 固定阈值要么误报要么漏报；用设备自己近期数据当基线，捕捉的是「相对自己的突变」，
 * 更贴近「这台臂最近不太对劲」的直觉，也好向答辩解释。
 */
@Service
public class AnomalyService {

    private static final Logger log = LoggerFactory.getLogger(AnomalyService.class);

    /** 一次最多扫多少帧，和历史曲线保持同一量级上限，防止大窗口把内存拉满。 */
    static final int MAX_RAW_SCAN = 20000;
    /** 异常点明细上限，超出只累计计数不再逐条返回，避免响应体过大。 */
    static final int MAX_POINTS = 500;
    /** 样本太少时基线没有统计意义，标记为 insufficient（仍返回，但调用方应弱化处理）。 */
    static final int MIN_SAMPLES = 30;
    /** std 低于此值视为「几乎不动」，不建带宽（否则任何微小抖动都超 kσ 误报）。 */
    private static final double MIN_STD = 1e-6;

    private static final String[] METRICS = {"effort", "velocity"};

    private final TelemetryRepository repository;
    private final ObjectMapper mapper = new ObjectMapper();

    public AnomalyService(TelemetryRepository repository) {
        this.repository = repository;
    }

    public AnomalyReport detect(Long deviceId, LocalDateTime from, LocalDateTime to, double sigma) {
        double k = sigma <= 0 ? 3.0 : sigma;
        List<TelemetryData> raw = repository.findSeries(deviceId, from, to, PageRequest.of(0, MAX_RAW_SCAN));
        int frames = raw.size();
        if (frames == 0) {
            return new AnomalyReport(deviceId, from, to, k, 0, false, 0, 0.0, List.of(), List.of());
        }

        // 第一遍：累计每关节每指标的 n / sum / sumSq，用于均值与标准差
        Map<String, Accumulator> acc = new LinkedHashMap<>();
        for (TelemetryData frame : raw) {
            forEachJointMetric(frame, (joint, metric, value) ->
                    acc.computeIfAbsent(key(joint, metric), key -> new Accumulator()).add(value));
        }

        List<AnomalyReport.JointBaseline> baselines = new ArrayList<>(acc.size());
        Map<String, double[]> bounds = new LinkedHashMap<>(); // key -> [mean, std, lower, upper]
        for (Map.Entry<String, Accumulator> entry : acc.entrySet()) {
            Accumulator a = entry.getValue();
            double mean = a.mean();
            double std = a.std();
            double lower = std < MIN_STD ? mean : mean - k * std;
            double upper = std < MIN_STD ? mean : mean + k * std;
            String[] parts = entry.getKey().split("\u0001", 2);
            baselines.add(new AnomalyReport.JointBaseline(parts[0], parts[1], round(mean), round(std),
                    round(lower), round(upper), a.n));
            bounds.put(entry.getKey(), new double[]{mean, std, lower, upper});
        }

        // 第二遍：回扫标记越界样本
        List<AnomalyReport.AnomalyPoint> points = new ArrayList<>();
        int anomalyFrames = 0;
        int totalAnomalies = 0;
        for (TelemetryData frame : raw) {
            boolean frameHasAnomaly = false;
            List<AnomalyReport.AnomalyPoint> framePoints = collectFrameAnomalies(frame, bounds);
            if (!framePoints.isEmpty()) {
                frameHasAnomaly = true;
                totalAnomalies += framePoints.size();
                for (AnomalyReport.AnomalyPoint p : framePoints) {
                    if (points.size() < MAX_POINTS) {
                        points.add(p);
                    }
                }
            }
            if (frameHasAnomaly) {
                anomalyFrames++;
            }
        }

        boolean sufficient = frames >= MIN_SAMPLES;
        double ratio = round((double) anomalyFrames / frames);
        log.debug("device {} anomaly scan: {} frames, {} anomaly frames, {} points ({} total)",
                deviceId, frames, anomalyFrames, points.size(), totalAnomalies);
        return new AnomalyReport(deviceId, from, to, k, frames, sufficient, anomalyFrames, ratio, baselines, points);
    }

    private List<AnomalyReport.AnomalyPoint> collectFrameAnomalies(TelemetryData frame, Map<String, double[]> bounds) {
        List<AnomalyReport.AnomalyPoint> found = new ArrayList<>();
        forEachJointMetric(frame, (joint, metric, value) -> {
            double[] b = bounds.get(key(joint, metric));
            if (b == null) {
                return;
            }
            double mean = b[0];
            double std = b[1];
            double lower = b[2];
            double upper = b[3];
            if (std < MIN_STD) {
                return; // 基本不动的关节不判异常
            }
            if (value < lower || value > upper) {
                double z = round((value - mean) / std);
                found.add(new AnomalyReport.AnomalyPoint(frame.getReportedAt(), joint, metric, round(value),
                        round(mean), z));
            }
        });
        return found;
    }

    /** 解析一帧的 joints 数组，对每个关节的 effort/velocity 回调。脏帧静默跳过。 */
    private void forEachJointMetric(TelemetryData frame, JointMetricConsumer consumer) {
        JsonNode payload = parse(frame.getJointPayload());
        if (payload == null || !payload.isArray()) {
            return;
        }
        for (JsonNode joint : payload) {
            String name = joint.path("name").asText(null);
            if (name == null) {
                continue;
            }
            for (String metric : METRICS) {
                JsonNode node = joint.path(metric);
                if (node.isNumber()) {
                    consumer.accept(name, metric, node.asDouble());
                }
            }
        }
    }

    private JsonNode parse(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return mapper.readTree(raw);
        } catch (Exception ex) {
            return null;
        }
    }

    private static String key(String joint, String metric) {
        return joint + "\u0001" + metric;
    }

    private static double round(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }

    @FunctionalInterface
    private interface JointMetricConsumer {
        void accept(String joint, String metric, double value);
    }

    /** 在线累计器：n / Σx / Σx² → 均值与总体标准差。 */
    private static final class Accumulator {
        private int n;
        private double sum;
        private double sumSq;

        void add(double value) {
            n++;
            sum += value;
            sumSq += value * value;
        }

        double mean() {
            return n == 0 ? 0 : sum / n;
        }

        double std() {
            if (n == 0) {
                return 0;
            }
            double mean = mean();
            double variance = Math.max(0, sumSq / n - mean * mean);
            return Math.sqrt(variance);
        }
    }
}
