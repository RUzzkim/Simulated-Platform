package com.platform.robotcloud.event;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 故障统计结果，from/to 为实际生效的查询区间。
 */
public record FaultStatistics(
        long total,
        LocalDateTime from,
        LocalDateTime to,
        List<FaultStatItem> byLevel,
        List<FaultStatItem> byType,
        List<FaultStatItem> byDay,
        List<DeviceFaultStat> byDevice) {
}