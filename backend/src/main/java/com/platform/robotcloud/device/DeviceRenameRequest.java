package com.platform.robotcloud.device;

import jakarta.validation.constraints.NotBlank;

public record DeviceRenameRequest(@NotBlank String name) {
}