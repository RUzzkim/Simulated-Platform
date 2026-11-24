package com.platform.robotcloud.security;

/**
 * 让 TokenAuthFilter 能校验边缘令牌是否仍有效（已吊销或轮换过的令牌立即失效），
 * 实现放在 credential 包，避免 security 反向依赖业务包。
 */
public interface EdgeTokenValidator {

    boolean isTokenActive(Long deviceId, int tokenVersion);
}