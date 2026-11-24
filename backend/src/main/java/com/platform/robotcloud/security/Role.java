package com.platform.robotcloud.security;

/**
 * 云端用户角色：ADMIN 管账号与全部操作，OPERATOR 管设备与指令，VIEWER 只读。
 * 边缘端/仿真端不走这里，它们用 edge token（scope=edge）单独鉴权。
 */
public enum Role {
    ADMIN,
    OPERATOR,
    VIEWER;

    public String authority() {
        return "ROLE_" + name();
    }

    public boolean canWrite() {
        return this == ADMIN || this == OPERATOR;
    }

    public static Role of(String raw) {
        if (raw == null || raw.isBlank()) {
            throw new IllegalArgumentException("role must not be blank");
        }
        try {
            return Role.valueOf(raw.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("unknown role: " + raw + " (expect ADMIN/OPERATOR/VIEWER)");
        }
    }
}