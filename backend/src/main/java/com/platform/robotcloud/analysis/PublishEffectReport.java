package com.platform.robotcloud.analysis;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 下发效果分析：对比某次下发「生效时刻前 vs 后」各关节 effort 的均值/波动，判断这次调参有没有用。
 *
 * <p>分界点取该指令的回执时刻（acknowledgedAt，缺失时兜底 issuedAt）。前后各取一段等长窗口，
 * 逐关节算均值/std 再比差异。语义是「下发这版参数/策略后，臂的负载表现有没有实际变化」，
 * 把「下发—回执」和「遥测」两条数据线接起来，形成闭环证据。
 *
 * @param commandId      command_log 记录 id
 * @param deviceId       设备 id
 * @param cmdType        指令类型（PARAMETER/STRATEGY/MODEL/...）
 * @param version        下发的版本号（无则 null）
 * @param publishedAt    生效分界点时刻
 * @param metric         对比指标（默认 effort）
 * @param windowMinutes  前/后各取的窗口分钟数
 * @param before         下发前各关节统计
 * @param after          下发后各关节统计
 * @param overallDelta   汇总均值变化（after 全关节均值 − before 全关节均值）
 * @param verdict        人话结论
 */
public record PublishEffectReport(
        Long commandId,
        Long deviceId,
        String cmdType,
        Integer version,
        LocalDateTime publishedAt,
        String metric,
        int windowMinutes,
        List<MetricStat> before,
        List<MetricStat> after,
        double overallDelta,
        String verdict) {

    /** 某关节在某侧窗口内的指标统计。 */
    public record MetricStat(String joint, double mean, double std, int samples) {
    }
}
