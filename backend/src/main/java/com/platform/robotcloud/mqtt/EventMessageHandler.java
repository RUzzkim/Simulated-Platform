package com.platform.robotcloud.mqtt;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.event.FaultEventService;
import org.springframework.stereotype.Component;

@Component
public class EventMessageHandler implements EdgeMessageHandler {

    private final FaultEventService service;

    public EventMessageHandler(FaultEventService service) {
        this.service = service;
    }

    @Override
    public String topicSuffix() {
        return "event";
    }

    @Override
    public void handle(JsonNode payload) {
        service.saveEvent(payload);
    }
}