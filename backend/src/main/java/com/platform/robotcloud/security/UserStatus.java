package com.platform.robotcloud.security;

/**
 * 账号审批状态：自助注册的账号先落 PENDING，ADMIN 审批后置 APPROVED 才能登录；
 * 驳回则置 REJECTED。ADMIN 直接建号或系统初始化的账号直接是 APPROVED。
 * 与 {@code enabled} 正交：enabled 管「已批准账号的临时停用」，status 管「是否放行入场」。
 */
public enum UserStatus {
    PENDING,
    APPROVED,
    REJECTED;

    public static UserStatus of(String raw) {
        if (raw == null || raw.isBlank()) {
            return APPROVED;
        }
        try {
            return UserStatus.valueOf(raw.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("unknown status: " + raw + " (expect PENDING/APPROVED/REJECTED)");
        }
    }
}
