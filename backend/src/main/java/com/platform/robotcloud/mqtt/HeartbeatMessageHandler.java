package com.platform.robotcloud.mqtt;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.heartbeat.HeartbeatService;
import org.springframework.stereotype.Component;

@Component
public class HeartbeatMessageHandler implements EdgeMessageHandler {

    private final HeartbeatService service;

    public HeartbeatMessageHandler(HeartbeatService service) {
        this.service = service;
    }

    @Override
    public String topicSuffix() {
        return "heartbeat";
    }

    @Override
    public void handle(JsonNode payload) {
        service.saveHeartbeat(payload);
    }
}