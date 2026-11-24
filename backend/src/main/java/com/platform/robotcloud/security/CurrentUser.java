package com.platform.robotcloud.security;

/**
 * 当前登录用户的轻量视图，作为 Authentication 的 principal。
 */
public record CurrentUser(Long id, String username, String displayName, String role) {

    public boolean isAdmin() {
        return Role.ADMIN.name().equals(role);
    }

    public boolean canWrite() {
        return Role.ADMIN.name().equals(role) || Role.OPERATOR.name().equals(role);
    }
}