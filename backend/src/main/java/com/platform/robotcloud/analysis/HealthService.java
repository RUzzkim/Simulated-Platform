package com.platform.robotcloud.analysis;

import com.platform.robotcloud.device.Device;
import com.platform.robotcloud.device.DeviceRepository;
import com.platform.robotcloud.event.FaultEventRepository;
import com.platform.robotcloud.heartbeat.DeviceHeartbeat;
import com.platform.robotcloud.heartbeat.DeviceHeartbeatRepository;
import com.platform.robotcloud.telemetry.TelemetryData;
import com.platform.robotcloud.telemetry.TelemetryRepository;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/**
 * 设备健康评分：把「可用性 / 故障 / 遥测异常」三条线归一化成 0~100 的分项，再加权成综合分。
 * 全部基于已有表（device / device_heartbeat / fault_event / telemetry_data）现算，无需新表。
 *
 * <p>设计取向：可解释优先。每个分项都能单独讲清怎么来的，综合分只是加权平均，
 * 这样运维看到低分能立刻知道扣在哪，答辩也不至于被问到黑盒。
 */
@Service
public class HealthService {

    /** 三个分项的权重，和为 1。故障与遥测更能反映「臂本身好不好」，权重高些。 */
    private static final double W_AVAILABILITY = 0.25;
    private static final double W_FAULT = 0.35;
    private static final double W_TELEMETRY = 0.40;

    /** 故障扣分权重：一条 CRITICAL 约等于 5 条 WARNING。窗口内加权和直接当扣分（封顶 100）。 */
    private static final int PENALTY_WARNING = 4;
    private static final int PENALTY_ERROR = 12;
    private static final int PENALTY_CRITICAL = 25;

    /** 心跳/遥测新鲜度阈值：≤fresh 记满分，≥stale 记 0，中间线性。 */
    private static final Duration FRESH = Duration.ofMinutes(2);
    private static final Duration STALE = Duration.ofMinutes(30);

    private static final int DEFAULT_WINDOW_HOURS = 24;
    private static final int MAX_WINDOW_HOURS = 24 * 30;

    private final DeviceRepository deviceRepository;
    private final FaultEventRepository faultRepository;
    private final TelemetryRepository telemetryRepository;
    private final DeviceHeartbeatRepository heartbeatRepository;
    private final AnomalyService anomalyService;

    public HealthService(DeviceRepository deviceRepository,
                         FaultEventRepository faultRepository,
                         TelemetryRepository telemetryRepository,
                         DeviceHeartbeatRepository heartbeatRepository,
                         AnomalyService anomalyService) {
        this.deviceRepository = deviceRepository;
        this.faultRepository = faultRepository;
        this.telemetryRepository = telemetryRepository;
        this.heartbeatRepository = heartbeatRepository;
        this.anomalyService = anomalyService;
    }

    /** 整机队健康总览，按综合分升序（最差的排前面，便于运维先处理）。 */
    public List<DeviceHealth> fleet(int windowHours) {
        int hours = clampHours(windowHours);
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime from = now.minusHours(hours);
        List<DeviceHealth> result = new ArrayList<>();
        for (Device device : deviceRepository.findAll()) {
            result.add(assess(device, from, now, hours));
        }
        result.sort(Comparator.comparingInt(DeviceHealth::score));
        return result;
    }

    public DeviceHealth assess(Long deviceId, int windowHours) {
        int hours = clampHours(windowHours);
        Device device = deviceRepository.findById(deviceId)
                .orElseThrow(() -> new IllegalArgumentException("device not found: " + deviceId));
        LocalDateTime now = LocalDateTime.now();
        return assess(device, now.minusHours(hours), now, hours);
    }

    private DeviceHealth assess(Device device, LocalDateTime from, LocalDateTime to, int hours) {
        List<String> notes = new ArrayList<>();
        Long id = device.getId();

        int availability = availabilityScore(device, to, notes);

        List<DeviceHealth.FaultCount> faultCounts = faultTally(id, from, to);
        int faultHealth = faultScore(faultCounts);

        AnomalyReport anomaly = anomalyService.detect(id, from, to, 3.0);
        int telemetryHealth = telemetryScore(anomaly, notes);
        List<DeviceHealth.JointAnomalySummary> topJoints = topAnomalyJoints(anomaly);

        double composite = availability * W_AVAILABILITY
                + faultHealth * W_FAULT
                + telemetryHealth * W_TELEMETRY;
        int score = clampScore((int) Math.round(composite));

        return new DeviceHealth(
                id,
                device.getDeviceCode(),
                device.getName(),
                score,
                grade(score),
                availability,
                faultHealth,
                telemetryHealth,
                faultCounts,
                topJoints,
                new DeviceHealth.Window(from, to, hours),
                to,
                notes);
    }

    /** 可用性：先看设备状态，再看最近一次心跳/遥测的新鲜度。 */
    private int availabilityScore(Device device, LocalDateTime now, List<String> notes) {
        String status = device.getStatus();
        LocalDateTime lastSeen = latestActivity(device.getId());
        if (lastSeen == null) {
            notes.add("窗口内无心跳/遥测记录");
            return 0;
        }
        long ageSec = Math.max(0, Duration.between(lastSeen, now).getSeconds());
        int freshness;
        if (ageSec <= FRESH.getSeconds()) {
            freshness = 100;
        } else if (ageSec >= STALE.getSeconds()) {
            freshness = 0;
            notes.add("最近一次上报已超过 " + STALE.toMinutes() + " 分钟");
        } else {
            double span = STALE.getSeconds() - FRESH.getSeconds();
            freshness = clampScore((int) Math.round(100 * (1 - (ageSec - FRESH.getSeconds()) / span)));
        }
        // 设备被显式标为 OFFLINE 时，可用性再打个对折，避免刚断开但心跳还没过期时虚高
        if (status != null && status.equalsIgnoreCase("OFFLINE")) {
            notes.add("设备状态为 OFFLINE");
            freshness = freshness / 2;
        }
        return freshness;
    }

    private LocalDateTime latestActivity(Long deviceId) {
        LocalDateTime latest = null;
        DeviceHeartbeat hb = heartbeatRepository.findFirstByDeviceIdOrderByReportedAtDesc(deviceId).orElse(null);
        if (hb != null) {
            latest = hb.getReportedAt();
        }
        TelemetryData tm = telemetryRepository.findFirstByDeviceIdOrderByReportedAtDesc(deviceId).orElse(null);
        if (tm != null && (latest == null || tm.getReportedAt().isAfter(latest))) {
            latest = tm.getReportedAt();
        }
        return latest;
    }

    private List<DeviceHealth.FaultCount> faultTally(Long deviceId, LocalDateTime from, LocalDateTime to) {
        List<DeviceHealth.FaultCount> counts = new ArrayList<>();
        for (FaultEventRepository.KeyCount item : faultRepository.countByLevel(deviceId, from, to)) {
            counts.add(new DeviceHealth.FaultCount(item.getKey(), item.getTotal()));
        }
        return counts;
    }

    private int faultScore(List<DeviceHealth.FaultCount> counts) {
        double penalty = 0;
        for (DeviceHealth.FaultCount c : counts) {
            penalty += weightFor(c.level()) * c.count();
        }
        return clampScore((int) Math.round(100 - Math.min(100, penalty)));
    }

    private int weightFor(String level) {
        if (level == null) {
            return PENALTY_WARNING;
        }
        return switch (level.toUpperCase()) {
            case "CRITICAL", "FATAL" -> PENALTY_CRITICAL;
            case "ERROR" -> PENALTY_ERROR;
            case "WARNING", "WARN" -> PENALTY_WARNING;
            default -> PENALTY_WARNING;
        };
    }

    private int telemetryScore(AnomalyReport anomaly, List<String> notes) {
        if (anomaly.framesScanned() == 0) {
            notes.add("窗口内无遥测数据，遥测分按满分计");
            return 100;
        }
        if (!anomaly.sufficient()) {
            notes.add("遥测样本较少（" + anomaly.framesScanned() + " 帧），异常基线仅供参考");
        }
        return clampScore((int) Math.round(100 * (1 - anomaly.anomalyRatio())));
    }

    /** 从异常点里挑出出现次数最多的前 3 个关节，给前端做「最该看哪个关节」的摘要。 */
    private List<DeviceHealth.JointAnomalySummary> topAnomalyJoints(AnomalyReport anomaly) {
        Map<String, int[]> counts = new java.util.LinkedHashMap<>();
        Map<String, Double> maxAbsZ = new java.util.LinkedHashMap<>();
        for (AnomalyReport.AnomalyPoint p : anomaly.points()) {
            counts.computeIfAbsent(p.joint(), key -> new int[1])[0]++;
            double absZ = Math.abs(p.zScore());
            maxAbsZ.merge(p.joint(), absZ, Math::max);
        }
        return counts.entrySet().stream()
                .map(e -> new DeviceHealth.JointAnomalySummary(e.getKey(), e.getValue()[0],
                        round(maxAbsZ.getOrDefault(e.getKey(), 0.0))))
                .sorted(Comparator.comparingInt(DeviceHealth.JointAnomalySummary::anomalyPoints).reversed())
                .limit(3)
                .toList();
    }

    private static String grade(int score) {
        if (score >= 90) {
            return "A";
        }
        if (score >= 75) {
            return "B";
        }
        if (score >= 60) {
            return "C";
        }
        return "D";
    }

    private static int clampScore(int value) {
        return Math.max(0, Math.min(100, value));
    }

    private int clampHours(int windowHours) {
        if (windowHours <= 0) {
            return DEFAULT_WINDOW_HOURS;
        }
        return Math.min(windowHours, MAX_WINDOW_HOURS);
    }

    private static double round(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }
}
