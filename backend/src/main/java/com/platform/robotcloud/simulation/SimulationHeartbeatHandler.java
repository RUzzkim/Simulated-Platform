package com.platform.robotcloud.simulation;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.heartbeat.HeartbeatService;
import com.platform.robotcloud.mqtt.EdgeMessageHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicLong;

/**
 * {@code simulation/{simulationId}/heartbeat}：边端心跳（ONLINE/OFFLINE，5s 一次）。
 * <p>边端的遗嘱报文 robotId 是空串（构建 MqttClient 时还不知道 robotId），
 * 归属不到设备，只能跳过——否则会凭空建出一条空设备。
 */
@Component
public class SimulationHeartbeatHandler implements EdgeMessageHandler {

    private static final Logger log = LoggerFactory.getLogger(SimulationHeartbeatHandler.class);

    private final EdgeContractAdapter adapter;
    private final HeartbeatService heartbeatService;
    private final DeviceLookupService deviceLookupService;
    private final AtomicLong unattributed = new AtomicLong();

    public SimulationHeartbeatHandler(EdgeContractAdapter adapter,
                                      HeartbeatService heartbeatService,
                                      DeviceLookupService deviceLookupService) {
        this.adapter = adapter;
        this.heartbeatService = heartbeatService;
        this.deviceLookupService = deviceLookupService;
    }

    @Override
    public String topicSuffix() {
        return "heartbeat";
    }

    @Override
    public boolean matches(String topic) {
        return SimulationTopics.simulationIdFromHeartbeat(topic) != null;
    }

    @Override
    public void handle(String topic, JsonNode payload) {
        String simulationId = SimulationTopics.simulationIdFromHeartbeat(topic);
        String robotId = EdgeContractAdapter.robotId(payload);
        if (robotId == null) {
            long total = unattributed.incrementAndGet();
            log.warn("simulation 心跳没有 robotId（边端遗嘱报文），跳过：sim={} status={}（累计 {} 条）",
                    simulationId, payload.path("status").asText("?"), total);
            return;
        }
        deviceLookupService.bindSimulation(robotId, simulationId);
        heartbeatService.saveHeartbeat(adapter.toHeartbeat(payload));
    }
}