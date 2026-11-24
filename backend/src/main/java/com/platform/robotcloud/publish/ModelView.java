package com.platform.robotcloud.publish;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.LocalDateTime;

public record ModelView(Long id, Long deviceId, String modelName, int version, String artifactUrl,
                        JsonNode metadata, String status, Long createdBy, String createdByName,
                        LocalDateTime createdAt) {
}