package com.platform.robotcloud.telemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 遥测归档（阶段 4）：把保留期之前的明细按「设备 + 小时」聚合成一行写到 telemetry_hourly，再删掉明细。
 *
 * <p>默认**不开**（app.telemetry.archive-enabled=false），也没在开发库里删过任何数据：
 * 线上要先跑 dryRun 看清影响面，再打开定时任务。删除是按批进行的（deleteAllInBatch），
 * 一次删 5000 行，避免长事务把 MySQL 拖住。
 */
@Service
public class TelemetryArchiveService {

    private static final Logger log = LoggerFactory.getLogger(TelemetryArchiveService.class);

    public record ArchiveResult(int retentionDays, LocalDateTime cutoff, boolean dryRun,
                               long candidates, int framesArchived, int bucketsWritten,
                               int devicesTouched, LocalDateTime finishedAt) {
    }

    private final TelemetryRepository repository;
    private final TelemetryHourlyRepository hourlyRepository;
    private final AuditService auditService;
    private final ObjectMapper mapper = new ObjectMapper();

    private final boolean enabled;
    private final int configuredRetentionDays;
    private final int batchSize;

    public TelemetryArchiveService(TelemetryRepository repository,
                                   TelemetryHourlyRepository hourlyRepository,
                                   AuditService auditService,
                                   @Value("${app.telemetry.archive-enabled:false}") boolean enabled,
                                   @Value("${app.telemetry.retention-days:30}") int configuredRetentionDays,
                                   @Value("${app.telemetry.archive-batch-size:5000}") int batchSize) {
        this.repository = repository;
        this.hourlyRepository = hourlyRepository;
        this.auditService = auditService;
        this.enabled = enabled;
        this.configuredRetentionDays = configuredRetentionDays;
        this.batchSize = Math.max(batchSize, 100);
    }

    @Scheduled(cron = "${app.telemetry.archive-cron:0 30 3 * * *}")
    public void scheduled() {
        if (!enabled) {
            return;
        }
        try {
            archive(configuredRetentionDays, false);
        } catch (Exception ex) {
            log.error("scheduled telemetry archive failed", ex);
        }
    }

    /**
     * @param retentionDays 保留最近多少天的明细；更早的归档
     * @param dryRun        true 只统计不写库不删除（线上先跑这个看影响面）
     */
    @Transactional
    public ArchiveResult archive(int retentionDays, boolean dryRun) {
        int days = Math.max(retentionDays, 1);
        LocalDateTime cutoff = LocalDateTime.now().minus(days, ChronoUnit.DAYS).truncatedTo(ChronoUnit.HOURS);
        long candidates = repository.countByReportedAtBefore(cutoff);
        Map<String, Bucket> buckets = new LinkedHashMap<>();
        Map<Long, Boolean> devices = new LinkedHashMap<>();
        int frames = 0;
        if (candidates > 0) {
            while (true) {
                List<TelemetryData> batch = repository.findByReportedAtBeforeOrderByReportedAtAsc(
                        cutoff, PageRequest.of(0, batchSize));
                if (batch.isEmpty()) {
                    break;
                }
                aggregate(batch, buckets);
                batch.forEach(frame -> devices.putIfAbsent(frame.getDeviceId(), Boolean.TRUE));
                frames += batch.size();
                if (dryRun) {
                    break;
                }
                repository.deleteAllInBatch(batch);
                if (batch.size() < batchSize) {
                    break;
                }
            }
        }
        int written = 0;
        if (!dryRun) {
            for (Bucket bucket : buckets.values()) {
                written += flush(bucket);
            }
        }
        ArchiveResult result = new ArchiveResult(days, cutoff, dryRun, candidates, frames,
                dryRun ? buckets.size() : written, devices.size(), LocalDateTime.now());
        auditService.userAction(AuditAction.TELEMETRY_ARCHIVE, "telemetry", "hourly",
                (dryRun ? "试运行归档：" : "归档：") + "保留 " + days + " 天，命中 " + candidates
                        + " 帧，写入 " + result.bucketsWritten() + " 个小时桶");
        log.info("telemetry archive {} cutoff={} candidates={} frames={} buckets={}",
                dryRun ? "dry-run" : "done", cutoff, candidates, frames, result.bucketsWritten());
        return result;
    }

    public long detailCount() {
        return repository.count();
    }

    public long hourlyCount() {
        return hourlyRepository.count();
    }

    public LocalDateTime lastArchivedAt() {
        return hourlyRepository.findTopByOrderByArchivedAtDesc()
                .map(TelemetryHourly::getArchivedAt)
                .orElse(null);
    }

    private void aggregate(List<TelemetryData> batch, Map<String, Bucket> buckets) {
        for (TelemetryData frame : batch) {
            LocalDateTime bucketStart = frame.getReportedAt().truncatedTo(ChronoUnit.HOURS);
            Bucket bucket = buckets.computeIfAbsent(frame.getDeviceId() + "|" + bucketStart,
                    key -> new Bucket(frame.getDeviceId(), bucketStart));
            bucket.frames++;
            bucket.state = frame.getState();
            bucket.controlMode = frame.getControlMode();
            JsonNode payload = parse(frame.getJointPayload());
            if (payload == null || !payload.isArray()) {
                continue;
            }
            for (JsonNode joint : payload) {
                String name = joint.path("name").asText(null);
                if (name == null) {
                    continue;
                }
                double[] acc = bucket.joints.computeIfAbsent(name, key -> new double[4]);
                acc[0] += joint.path("position").asDouble(0);
                acc[1] += joint.path("velocity").asDouble(0);
                acc[2] += joint.path("effort").asDouble(0);
                acc[3] += 1;
            }
        }
    }

    /** 同一个小时桶已存在时按帧数加权合并，避免重复跑归档把均值算错。 */
    private int flush(Bucket bucket) {
        TelemetryHourly row = hourlyRepository
                .findByDeviceIdAndBucketStart(bucket.deviceId, bucket.bucketStart)
                .orElseGet(() -> {
                    TelemetryHourly created = new TelemetryHourly();
                    created.setDeviceId(bucket.deviceId);
                    created.setBucketStart(bucket.bucketStart);
                    created.setFrameCount(0);
                    created.setJointMetrics("{\"count\":0,\"joints\":[]}");
                    return created;
                });
        Map<String, double[]> merged = readJoints(row.getJointMetrics());
        int existingCount = row.getFrameCount() == null ? 0 : row.getFrameCount();
        for (Map.Entry<String, double[]> entry : bucket.joints.entrySet()) {
            double[] target = merged.computeIfAbsent(entry.getKey(), key -> new double[4]);
            double[] source = entry.getValue();
            target[0] += source[0];
            target[1] += source[1];
            target[2] += source[2];
            target[3] += source[3];
        }
        row.setFrameCount(existingCount + bucket.frames);
        row.setState(bucket.state);
        row.setControlMode(bucket.controlMode);
        row.setJointMetrics(writeJoints(merged, row.getFrameCount()));
        row.setArchivedAt(LocalDateTime.now());
        hourlyRepository.save(row);
        return 1;
    }

    private Map<String, double[]> readJoints(String json) {
        Map<String, double[]> result = new LinkedHashMap<>();
        JsonNode node = parse(json);
        if (node == null) {
            return result;
        }
        JsonNode joints = node.path("joints");
        if (!joints.isArray()) {
            return result;
        }
        for (JsonNode joint : joints) {
            String name = joint.path("name").asText(null);
            if (name == null) {
                continue;
            }
            double[] acc = new double[4];
            double samples = joint.path("samples").asDouble(1);
            acc[0] = joint.path("position").asDouble(0) * samples;
            acc[1] = joint.path("velocity").asDouble(0) * samples;
            acc[2] = joint.path("effort").asDouble(0) * samples;
            acc[3] = samples;
            result.put(name, acc);
        }
        return result;
    }

    private String writeJoints(Map<String, double[]> joints, int frameCount) {
        ArrayNode array = mapper.createArrayNode();
        for (Map.Entry<String, double[]> entry : joints.entrySet()) {
            double[] acc = entry.getValue();
            if (acc[3] <= 0) {
                continue;
            }
            ObjectNode node = array.addObject();
            node.put("name", entry.getKey());
            node.put("position", round(acc[0] / acc[3]));
            node.put("velocity", round(acc[1] / acc[3]));
            node.put("effort", round(acc[2] / acc[3]));
            node.put("samples", (int) acc[3]);
        }
        ObjectNode root = mapper.createObjectNode();
        root.put("count", frameCount);
        root.set("joints", array);
        return root.toString();
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

    private static double round(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }

    private static final class Bucket {
        private final Long deviceId;
        private final LocalDateTime bucketStart;
        private final Map<String, double[]> joints = new LinkedHashMap<>();
        private int frames;
        private String state;
        private String controlMode;

        private Bucket(Long deviceId, LocalDateTime bucketStart) {
            this.deviceId = deviceId;
            this.bucketStart = bucketStart;
        }
    }

    /** 供测试/排查用：列出归档表里的桶。 */
    public List<TelemetryHourly> hourly(Long deviceId, LocalDateTime from, LocalDateTime to) {
        return hourlyRepository.findByDeviceIdAndBucketStartBetweenOrderByBucketStartAsc(deviceId, from, to);
    }

}