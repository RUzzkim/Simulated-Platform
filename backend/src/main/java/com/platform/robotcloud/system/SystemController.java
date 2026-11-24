package com.platform.robotcloud.system;

import com.platform.robotcloud.audit.AuditLogRepository;
import com.platform.robotcloud.device.DeviceRepository;
import com.platform.robotcloud.mqtt.MqttMessageRouter;
import com.platform.robotcloud.telemetry.TelemetryArchiveService;
import com.platform.robotcloud.telemetry.TelemetryBatchWriter;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.lang.management.ManagementFactory;
import java.time.LocalDateTime;

@RestController
@RequestMapping("/api/system")
public class SystemController {

    public record Stats(TelemetryBatchWriter.Stats telemetryWriter,
                        MqttMessageRouter.Stats mqttRouter,
                        long deviceTotal,
                        long deviceOnline,
                        long auditTotal,
                        Telemetry telemetry,
                        long uptimeSeconds) {
    }

    /** 遥测明细/归档水位：明细持续涨说明该调归档保留期，dropped 涨说明队列要调大。 */
    public record Telemetry(long detailRows, long hourlyRows, LocalDateTime lastArchivedAt) {
    }

    private final TelemetryBatchWriter telemetryBatchWriter;
    private final MqttMessageRouter mqttMessageRouter;
    private final DeviceRepository deviceRepository;
    private final AuditLogRepository auditLogRepository;
    private final TelemetryArchiveService archiveService;

    public SystemController(TelemetryBatchWriter telemetryBatchWriter,
                            MqttMessageRouter mqttMessageRouter,
                            DeviceRepository deviceRepository,
                            AuditLogRepository auditLogRepository,
                            TelemetryArchiveService archiveService) {
        this.telemetryBatchWriter = telemetryBatchWriter;
        this.mqttMessageRouter = mqttMessageRouter;
        this.deviceRepository = deviceRepository;
        this.auditLogRepository = auditLogRepository;
        this.archiveService = archiveService;
    }

    @GetMapping("/stats")
    public Stats stats() {
        return new Stats(
                telemetryBatchWriter.stats(),
                mqttMessageRouter.stats(),
                deviceRepository.count(),
                deviceRepository.findByStatusOrderByIdAsc("ONLINE").size(),
                auditLogRepository.count(),
                new Telemetry(archiveService.detailCount(), archiveService.hourlyCount(),
                        archiveService.lastArchivedAt()),
                ManagementFactory.getRuntimeMXBean().getUptime() / 1000);
    }

    /**
     * 手动触发遥测归档（默认 dryRun=true，只统计不删数据）。
     * 线上流程：先 dryRun 看命中多少帧，再 retentionDays + dryRun=false 真归档。
     */
    @PostMapping("/archive")
    public TelemetryArchiveService.ArchiveResult archive(
            @RequestParam(defaultValue = "30") int retentionDays,
            @RequestParam(defaultValue = "true") boolean dryRun) {
        return archiveService.archive(retentionDays, dryRun);
    }
}