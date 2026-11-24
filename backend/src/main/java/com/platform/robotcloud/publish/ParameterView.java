package com.platform.robotcloud.publish;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.LocalDateTime;

public record ParameterView(Long id, Long deviceId, int version, JsonNode payload, String status,
                            Long createdBy, String createdByName, LocalDateTime createdAt) {
}