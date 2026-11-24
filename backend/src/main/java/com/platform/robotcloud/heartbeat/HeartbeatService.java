package com.platform.robotcloud.heartbeat;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.support.Payloads;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Optional;

@Service
public class HeartbeatService {

    private final DeviceHeartbeatRepository repository;
    private final DeviceLookupService deviceLookupService;

    public HeartbeatService(DeviceHeartbeatRepository repository, DeviceLookupService deviceLookupService) {
        this.repository = repository;
        this.deviceLookupService = deviceLookupService;
    }

    public void saveHeartbeat(JsonNode json) {
        String deviceCode = Payloads.deviceCode(json);
        if (deviceCode == null) {
            throw new IllegalArgumentException("heartbeat payload has no deviceId");
        }
        Long deviceId = deviceLookupService.findOrCreateId(deviceCode);

        DeviceHeartbeat heartbeat = new DeviceHeartbeat();
        heartbeat.setDeviceId(deviceId);
        heartbeat.setStatus(Payloads.text(json, "status", "ONLINE"));
        heartbeat.setCpuUsage(Payloads.decimal(json, "cpu"));
        heartbeat.setMemoryUsage(Payloads.decimal(json, "memory"));
        heartbeat.setEdgeVersion(Payloads.text(json, "edgeVersion", null));
        heartbeat.setReportedAt(Payloads.reportedAt(json));
        repository.save(heartbeat);

        deviceLookupService.markOnline(deviceId, heartbeat.getStatus(), heartbeat.getReportedAt());
    }

    public Optional<DeviceHeartbeat> latest(Long deviceId) {
        return repository.findFirstByDeviceIdOrderByReportedAtDesc(deviceId);
    }
}