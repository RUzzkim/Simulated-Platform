package com.platform.robotcloud.publish;

/**
 * 版本状态机（参数 / 策略 / 模型共用）。
 *
 * <p>DRAFT 创建后未下发 → PUBLISHED 已下发待回执 → ACTIVE 边缘端回执成功（当前生效）
 * → SUPERSEDED 被同范围内更新的版本取代；下发失败保持 PUBLISHED，回执结果在 command_log 里查。
 */
public final class PublishStatus {

    public static final String DRAFT = "DRAFT";
    public static final String PUBLISHED = "PUBLISHED";
    public static final String ACTIVE = "ACTIVE";
    public static final String SUPERSEDED = "SUPERSEDED";

    private PublishStatus() {
    }
}