package com.platform.robotcloud.mqtt;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.telemetry.TelemetryService;
import org.springframework.stereotype.Component;

@Component
public class TelemetryMessageHandler implements EdgeMessageHandler {

    private final TelemetryService service;

    public TelemetryMessageHandler(TelemetryService service) {
        this.service = service;
    }

    @Override
    public String topicSuffix() {
        return "telemetry";
    }

    @Override
    public void handle(JsonNode payload) {
        service.saveTelemetry(payload);
    }
}