package com.platform.robotcloud.security;

/**
 * 边缘端/仿真端令牌对应的身份，只允许访问 /api/edge/**。
 */
public record EdgePrincipal(Long deviceId, String deviceCode) {
}