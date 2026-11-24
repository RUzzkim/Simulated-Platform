package com.platform.robotcloud.analysis;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 单设备遥测异常检测结果。基线按窗口内每关节 effort/velocity 的均值 ± kσ 计算，
 * 越界的帧记为异常点。语义是「相对该设备自身近期基线的统计离群」，
 * 与边端的规则式故障（阈值 + 边沿检测）互补，不是同一回事。
 *
 * @param deviceId       设备 id
 * @param from           实际生效的窗口起点
 * @param to             实际生效的窗口终点
 * @param sigma          判定用的 σ 倍数
 * @param framesScanned  参与统计的遥测帧数
 * @param sufficient     样本是否足够（帧数 &ge; 最小样本数），不足时基线仅供参考
 * @param anomalyFrames  含至少一个越界关节的帧数
 * @param anomalyRatio   anomalyFrames / framesScanned，0~1
 * @param baselines      每关节每指标（effort/velocity）的基线
 * @param points         越界异常点明细（按时间升序，最多 {@code MAX_POINTS} 条）
 */
public record AnomalyReport(
        Long deviceId,
        LocalDateTime from,
        LocalDateTime to,
        double sigma,
        int framesScanned,
        boolean sufficient,
        int anomalyFrames,
        double anomalyRatio,
        List<JointBaseline> baselines,
        List<AnomalyPoint> points) {

    /** 每关节 + 指标的统计基线。metric ∈ {effort, velocity}。 */
    public record JointBaseline(String joint, String metric, double mean, double std,
                                double lower, double upper, int samples) {
    }

    /** 一个越界样本：某帧某关节某指标超出 [lower, upper]。zScore 为偏离基线的 σ 数。 */
    public record AnomalyPoint(LocalDateTime at, String joint, String metric, double value,
                               double mean, double zScore) {
    }
}
