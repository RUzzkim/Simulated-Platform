package com.platform.robotcloud.device;

import jakarta.validation.constraints.NotBlank;

public record DeviceRequest(@NotBlank String deviceCode, String name) {
}