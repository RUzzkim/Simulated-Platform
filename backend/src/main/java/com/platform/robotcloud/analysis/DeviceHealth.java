package com.platform.robotcloud.analysis;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 单设备健康评估结果：0~100 综合分 + A/B/C/D 分级 + 三个分项，外加最近异常关节摘要。
 *
 * <p>综合分 = 可用性分 × w_avail + 故障分 × w_fault + 遥测分 × w_telemetry（权重见 {@link HealthService}）。
 * 每个分项都 0~100、越高越好，好处是能直接告诉运维「扣分主要扣在哪」，而不是给一个黑盒数字。
 *
 * @param deviceId     设备 id
 * @param deviceCode   设备编号
 * @param name         设备名
 * @param score        综合健康分 0~100
 * @param grade        分级 A(≥90)/B(≥75)/C(≥60)/D(&lt;60)
 * @param availability 可用性分（在线/心跳新鲜度）
 * @param faultHealth  故障分（窗口内按等级加权扣分）
 * @param telemetryHealth 遥测分（100 × (1 − 异常帧占比)）
 * @param faultCounts  窗口内各等级故障计数（WARNING/ERROR/CRITICAL）
 * @param topAnomalyJoints 异常最多的关节摘要（最多 3 个）
 * @param window       评估窗口
 * @param evaluatedAt  评估时刻
 * @param notes        说明（如样本不足、设备离线）
 */
public record DeviceHealth(
        Long deviceId,
        String deviceCode,
        String name,
        int score,
        String grade,
        int availability,
        int faultHealth,
        int telemetryHealth,
        List<FaultCount> faultCounts,
        List<JointAnomalySummary> topAnomalyJoints,
        Window window,
        LocalDateTime evaluatedAt,
        List<String> notes) {

    public record FaultCount(String level, long count) {
    }

    public record JointAnomalySummary(String joint, int anomalyPoints, double maxAbsZ) {
    }

    public record Window(LocalDateTime from, LocalDateTime to, int hours) {
    }
}
