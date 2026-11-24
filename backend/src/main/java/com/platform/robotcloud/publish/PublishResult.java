package com.platform.robotcloud.publish;

/**
 * 一次下发的返回：messageId 用于与边缘端回执对应，status 是版本行当前状态。
 */
public record PublishResult(String kind, int version, String messageId, String status, String commandResult,
                            boolean rollback) {
}