package com.platform.robotcloud.audit;

/**
 * 审计动作常量：用户侧（REST 操作）与边缘侧（设备上报/回执）统一编码，便于按动作检索。
 */
public final class AuditAction {

    public static final String LOGIN = "LOGIN";
    public static final String PASSWORD_CHANGE = "PASSWORD_CHANGE";
    public static final String USER_CREATE = "USER_CREATE";
    public static final String USER_UPDATE = "USER_UPDATE";
    public static final String USER_REGISTER = "USER_REGISTER";
    public static final String USER_APPROVE = "USER_APPROVE";
    public static final String USER_REJECT = "USER_REJECT";
    public static final String DEVICE_REGISTER = "DEVICE_REGISTER";
    public static final String DEVICE_RENAME = "DEVICE_RENAME";
    public static final String COMMAND_DISPATCH = "COMMAND_DISPATCH";
    public static final String COMMAND_ACK = "COMMAND_ACK";
    public static final String CREDENTIAL_ISSUE = "CREDENTIAL_ISSUE";
    public static final String CREDENTIAL_REVOKE = "CREDENTIAL_REVOKE";
    public static final String CREDENTIAL_READ = "CREDENTIAL_READ";
    public static final String EDGE_EVENT = "EDGE_EVENT";
    public static final String ADMIN_BOOTSTRAP = "ADMIN_BOOTSTRAP";
    // 阶段 4：参数 / 策略 / 模型的版本化与下发
    public static final String PARAMETER_CREATE = "PARAMETER_CREATE";
    public static final String PARAMETER_PUBLISH = "PARAMETER_PUBLISH";
    public static final String PARAMETER_APPLIED = "PARAMETER_APPLIED";
    public static final String STRATEGY_CREATE = "STRATEGY_CREATE";
    public static final String STRATEGY_PUBLISH = "STRATEGY_PUBLISH";
    public static final String STRATEGY_APPLIED = "STRATEGY_APPLIED";
    public static final String MODEL_CREATE = "MODEL_CREATE";
    public static final String MODEL_PUBLISH = "MODEL_PUBLISH";
    public static final String MODEL_APPLIED = "MODEL_APPLIED";
    // 阶段 4：遥测归档
    public static final String TELEMETRY_ARCHIVE = "TELEMETRY_ARCHIVE";

    private AuditAction() {
    }
}