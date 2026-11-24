package com.platform.robotcloud.publish;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.LocalDateTime;

public record StrategyView(Long id, String name, int version, JsonNode payload, String status,
                           Long createdBy, String createdByName, LocalDateTime createdAt) {
}