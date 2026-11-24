package com.platform.robotcloud.simulation;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.mqtt.EdgeMessageHandler;
import com.platform.robotcloud.support.Payloads;
import com.platform.robotcloud.telemetry.TelemetryService;
import org.springframework.stereotype.Component;

/**
 * {@code simulation/{simulationId}/state}：边端上传的机械臂状态。
 * <p>归一化后交给既有的 TelemetryService，所以批量写入、归档、降采样、前端曲线全部复用。
 */
@Component
public class SimulationStateHandler implements EdgeMessageHandler {

    private final EdgeContractAdapter adapter;
    private final TelemetryService telemetryService;
    private final DeviceLookupService deviceLookupService;
    private final SimulationFaultTracker faultTracker;

    public SimulationStateHandler(EdgeContractAdapter adapter,
                                  TelemetryService telemetryService,
                                  DeviceLookupService deviceLookupService,
                                  SimulationFaultTracker faultTracker) {
        this.adapter = adapter;
        this.telemetryService = telemetryService;
        this.deviceLookupService = deviceLookupService;
        this.faultTracker = faultTracker;
    }

    @Override
    public String topicSuffix() {
        return "state";
    }

    @Override
    public boolean matches(String topic) {
        return SimulationTopics.simulationIdFromState(topic) != null;
    }

    @Override
    public void handle(String topic, JsonNode payload) {
        String simulationId = SimulationTopics.simulationIdFromState(topic);
        String robotId = EdgeContractAdapter.robotId(payload);
        if (robotId == null) {
            throw new IllegalArgumentException("simulation state payload has no robotId");
        }
        // 先绑归属：设备是这一步首次创建的，后面遥测/故障都挂同一个 deviceId
        deviceLookupService.bindSimulation(robotId, simulationId);
        telemetryService.saveTelemetry(adapter.toTelemetry(payload));
        faultTracker.record(robotId, simulationId, adapter.faults(payload), Payloads.reportedAt(payload));
    }
}