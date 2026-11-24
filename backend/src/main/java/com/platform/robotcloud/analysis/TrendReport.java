package com.platform.robotcloud.analysis;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 单设备趋势 / 预测性维护结果。对窗口内每关节的 effort 做等时间分桶取均值、再线性回归求斜率，
 * 用「设备自身基线上界（mean+kσ，来自异常检测）」当危险线，外推「照当前趋势多久触及上界」。
 *
 * <p>语义是「这台臂的负载/磨损相对自己近期基线在往哪个方向走、多快」，可解释、便于答辩，
 * 与异常检测（当下越界与否）、健康评分（当前状态好坏）互补——趋势回答的是「未来会不会变坏」。
 *
 * @param deviceId       设备 id
 * @param from           实际生效的窗口起点
 * @param to             实际生效的窗口终点
 * @param metric         趋势指标（当前固定 effort）
 * @param buckets        等时间分桶数
 * @param framesScanned  参与统计的遥测帧数
 * @param sufficient     样本是否足够（帧数 &ge; 最小样本数），不足时趋势仅供参考
 * @param trends         每关节的趋势明细
 */
public record TrendReport(
        Long deviceId,
        LocalDateTime from,
        LocalDateTime to,
        String metric,
        int buckets,
        int framesScanned,
        boolean sufficient,
        List<JointTrend> trends) {

    /**
     * 单关节趋势。
     *
     * @param joint         关节名
     * @param metric        指标名（effort）
     * @param slopePerHour  线性回归斜率，单位/小时；&gt;0 表示在上升
     * @param current       最近一桶的均值（视为当前水平）
     * @param mean          窗口内基线均值
     * @param upperBound    基线上界 mean+kσ（危险线）
     * @param hoursToUpper  照当前斜率还有多久触及上界；斜率&le;0 或已越界时为 null
     * @param projection    人话结论
     * @param sampleBuckets 各桶均值（按时间升序），供前端画趋势折线
     */
    public record JointTrend(
            String joint,
            String metric,
            double slopePerHour,
            double current,
            double mean,
            double upperBound,
            Double hoursToUpper,
            String projection,
            List<Bucket> sampleBuckets) {
    }

    /** 一个时间桶：中点时刻 + 该桶内指标均值 + 原始帧数。 */
    public record Bucket(LocalDateTime at, double value, int samples) {
    }
}
