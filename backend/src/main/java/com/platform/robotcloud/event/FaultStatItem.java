package com.platform.robotcloud.event;

/**
 * 故障统计的「分组 + 计数」条目，key 可以是等级、类型或日期。
 */
public record FaultStatItem(String key, long count) {
}