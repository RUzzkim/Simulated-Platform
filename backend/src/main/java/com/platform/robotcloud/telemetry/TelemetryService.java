package com.platform.robotcloud.telemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.support.Payloads;
import org.springframework.stereotype.Service;

@Service
public class TelemetryService {

    private final DeviceLookupService deviceLookupService;
    private final TelemetryBatchWriter batchWriter;

    public TelemetryService(DeviceLookupService deviceLookupService, TelemetryBatchWriter batchWriter) {
        this.deviceLookupService = deviceLookupService;
        this.batchWriter = batchWriter;
    }

    public TelemetryData saveTelemetry(JsonNode json) {
        String deviceCode = Payloads.deviceCode(json);
        if (deviceCode == null) {
            throw new IllegalArgumentException("telemetry payload has no deviceId");
        }
        Long deviceId = deviceLookupService.findOrCreateId(deviceCode);

        TelemetryData entity = new TelemetryData();
        entity.setDeviceId(deviceId);
        entity.setReportedAt(Payloads.reportedAt(json));
        entity.setState(Payloads.text(json, "state", null));
        entity.setControlMode(Payloads.text(json, "controlMode", null));
        JsonNode joints = json.path("joints");
        entity.setJointPayload(joints.isArray() ? joints.toString() : "[]");
        entity.setEndEffectorPayload(Payloads.jsonOrNull(json, "endEffector"));

        // 高频遥测不在这里落库：交给 TelemetryBatchWriter 攒批写，设备状态也由它批量刷新
        batchWriter.enqueue(entity);
        return entity;
    }
}