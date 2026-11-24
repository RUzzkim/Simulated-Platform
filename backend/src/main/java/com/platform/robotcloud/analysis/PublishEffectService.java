package com.platform.robotcloud.analysis;

import com.platform.robotcloud.command.CommandLog;
import com.platform.robotcloud.command.CommandLogRepository;
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
 * 下发效果分析：拿某条下发指令的回执时刻当分界点，对比前后各一段窗口内 effort 的均值/波动。
 * 纯计算，跑在已有 command_log + telemetry_data 上。
 */
@Service
public class PublishEffectService {

    private static final Logger log = LoggerFactory.getLogger(PublishEffectService.class);

    private static final int MAX_RAW_SCAN = 20000;
    private static final int DEFAULT_WINDOW_MINUTES = 30;
    private static final int MAX_WINDOW_MINUTES = 24 * 60;
    private static final String DEFAULT_METRIC = "effort";
    /** 均值相对变化超过此比例才判「有变化」，否则算「无明显变化」。 */
    private static final double SIGNIFICANT_RATIO = 0.05;

    private final CommandLogRepository commandRepository;
    private final TelemetryRepository telemetryRepository;

    public PublishEffectService(CommandLogRepository commandRepository, TelemetryRepository telemetryRepository) {
        this.commandRepository = commandRepository;
        this.telemetryRepository = telemetryRepository;
    }

    public PublishEffectReport evaluate(Long commandId, String metric, int windowMinutes) {
        String m = (metric == null || metric.isBlank()) ? DEFAULT_METRIC : metric.trim();
        int win = windowMinutes <= 0 ? DEFAULT_WINDOW_MINUTES : Math.min(windowMinutes, MAX_WINDOW_MINUTES);

        CommandLog cmd = commandRepository.findById(commandId)
                .orElseThrow(() -> new IllegalArgumentException("command not found: " + commandId));

        // 分界点：优先回执时刻，缺失则用下发时刻兜底。
        LocalDateTime t0 = cmd.getAcknowledgedAt() != null ? cmd.getAcknowledgedAt() : cmd.getIssuedAt();
        Long deviceId = cmd.getDeviceId();

        List<MetricStatBuilder> beforeStats = collect(deviceId, t0.minusMinutes(win), t0, m);
        List<MetricStatBuilder> afterStats = collect(deviceId, t0, t0.plusMinutes(win), m);

        List<PublishEffectReport.MetricStat> before = toStats(beforeStats);
        List<PublishEffectReport.MetricStat> after = toStats(afterStats);

        double overallDelta = JointMetrics.round(overallMean(afterStats) - overallMean(beforeStats));
        String verdict = verdict(cmd, before, after, overallDelta, m);

        log.debug("command {} effect: metric={} window={}min before={}关节 after={}关节 delta={}",
                commandId, m, win, before.size(), after.size(), overallDelta);
        return new PublishEffectReport(
                commandId, deviceId, cmd.getCmdType(), cmd.getVersion(), t0, m, win,
                before, after, overallDelta, verdict);
    }

    private List<MetricStatBuilder> collect(Long deviceId, LocalDateTime from, LocalDateTime to, String metric) {
        List<TelemetryData> raw = telemetryRepository.findSeries(deviceId, from, to, PageRequest.of(0, MAX_RAW_SCAN));
        Map<String, JointMetrics.Accumulator> acc = new LinkedHashMap<>();
        for (TelemetryData frame : raw) {
            JointMetrics.forEach(frame, (joint, mtr, value) -> {
                if (metric.equals(mtr)) {
                    acc.computeIfAbsent(joint, key -> new JointMetrics.Accumulator()).add(value);
                }
            });
        }
        List<MetricStatBuilder> out = new ArrayList<>();
        for (Map.Entry<String, JointMetrics.Accumulator> e : acc.entrySet()) {
            out.add(new MetricStatBuilder(e.getKey(), e.getValue()));
        }
        return out;
    }

    private static List<PublishEffectReport.MetricStat> toStats(List<MetricStatBuilder> builders) {
        List<PublishEffectReport.MetricStat> out = new ArrayList<>(builders.size());
        for (MetricStatBuilder b : builders) {
            out.add(new PublishEffectReport.MetricStat(b.joint,
                    JointMetrics.round(b.acc.mean()), JointMetrics.round(b.acc.std()), b.acc.count()));
        }
        return out;
    }

    private static double overallMean(List<MetricStatBuilder> builders) {
        double sum = 0;
        int n = 0;
        for (MetricStatBuilder b : builders) {
            sum += b.acc.mean() * b.acc.count();
            n += b.acc.count();
        }
        return n == 0 ? 0 : sum / n;
    }

    private String verdict(CommandLog cmd, List<PublishEffectReport.MetricStat> before,
                           List<PublishEffectReport.MetricStat> after, double overallDelta, String metric) {
        if (!"SUCCESS".equalsIgnoreCase(cmd.getResult())) {
            return "该指令未成功回执（当前状态 " + cmd.getResult() + "），效果分析仅供参考";
        }
        if (before.isEmpty() || after.isEmpty()) {
            return "下发前后遥测样本不足，无法判定效果";
        }
        double beforeMean = overallMean0(before);
        if (Math.abs(beforeMean) < 1e-9) {
            return overallDelta == 0 ? "下发前后无明显变化" : String.format("%s 平均变化 %+.3f", metric, overallDelta);
        }
        double ratio = overallDelta / Math.abs(beforeMean);
        if (Math.abs(ratio) < SIGNIFICANT_RATIO) {
            return String.format("下发后 %s 均值基本持平（变化 %+.1f%%），无明显效果", metric, ratio * 100);
        }
        String dir = ratio < 0 ? "下降" : "上升";
        return String.format("下发后各关节 %s 均值%s %.1f%%（%+.3f），有明显变化", metric, dir, Math.abs(ratio) * 100, overallDelta);
    }

    private static double overallMean0(List<PublishEffectReport.MetricStat> stats) {
        double sum = 0;
        int n = 0;
        for (PublishEffectReport.MetricStat s : stats) {
            sum += s.mean() * s.samples();
            n += s.samples();
        }
        return n == 0 ? 0 : sum / n;
    }

    private record MetricStatBuilder(String joint, JointMetrics.Accumulator acc) {
    }
}
