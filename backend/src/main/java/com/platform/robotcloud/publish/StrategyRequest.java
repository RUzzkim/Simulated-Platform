package com.platform.robotcloud.publish;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record StrategyRequest(@NotBlank String name, @NotNull JsonNode payload) {
}