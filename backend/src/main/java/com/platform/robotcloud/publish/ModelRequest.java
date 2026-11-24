package com.platform.robotcloud.publish;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;

public record ModelRequest(@NotBlank String modelName, String artifactUrl, JsonNode metadata) {
}