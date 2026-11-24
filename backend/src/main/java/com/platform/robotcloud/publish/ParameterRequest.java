package com.platform.robotcloud.publish;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotNull;

public record ParameterRequest(@NotNull JsonNode payload) {
}