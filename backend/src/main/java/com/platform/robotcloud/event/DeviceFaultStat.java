package com.platform.robotcloud.event;

/**
 * 按设备聚合的故障计数，deviceCode/deviceName 取自 device 表。
 */
public record DeviceFaultStat(Long deviceId, String deviceCode, String deviceName, long count) {
}