package com.platform.robotcloud.analysis;

import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 云端分析：设备健康评分与遥测异常检测。
 * 全部只读（GET），任意已登录角色可看；计算跑在已有遥测/故障/心跳数据上，无副作用。
 */
@RestController
@RequestMapping("/api/analysis")
public class AnalysisController {

    private final HealthService healthService;
    private final AnomalyService anomalyService;
    private final TrendService trendService;
    private final PublishEffectService publishEffectService;

    public AnalysisController(HealthService healthService, AnomalyService anomalyService,
                              TrendService trendService, PublishEffectService publishEffectService) {
        this.healthService = healthService;
        this.anomalyService = anomalyService;
        this.trendService = trendService;
        this.publishEffectService = publishEffectService;
    }

    /** 机队健康总览，按综合分升序（最差在前）。windowHours 默认 24，上限 720（30 天）。 */
    @GetMapping("/health")
    public List<DeviceHealth> fleetHealth(@RequestParam(defaultValue = "24") int windowHours) {
        return healthService.fleet(windowHours);
    }

    /** 单设备健康评估（分项 + 最近异常关节摘要）。 */
    @GetMapping("/devices/{id}/health")
    public DeviceHealth deviceHealth(@PathVariable Long id,
                                     @RequestParam(defaultValue = "24") int windowHours) {
        return healthService.assess(id, windowHours);
    }

    /**
     * 单设备遥测异常检测。默认取最近 windowHours 小时（默认 24），也可显式传 from/to；
     * sigma 为判定用的 σ 倍数（默认 3）。
     */
    @GetMapping("/devices/{id}/anomalies")
    public AnomalyReport anomalies(
            @PathVariable Long id,
            @RequestParam(defaultValue = "24") int windowHours,
            @RequestParam(defaultValue = "3") double sigma,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to) {
        LocalDateTime now = LocalDateTime.now();
        int hours = windowHours <= 0 ? 24 : windowHours;
        LocalDateTime start = from != null ? from : now.minusHours(hours);
        LocalDateTime end = to != null ? to : now;
        return anomalyService.detect(id, start, end, sigma);
    }

    /**
     * 单设备趋势 / 预测性维护：对每关节 effort 分桶回归求斜率，用基线上界外推「多久到危险线」。
     * windowHours 默认 24，buckets 默认 12。
     */
    @GetMapping("/devices/{id}/trend")
    public TrendReport trend(
            @PathVariable Long id,
            @RequestParam(defaultValue = "24") int windowHours,
            @RequestParam(defaultValue = "12") int buckets,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to) {
        LocalDateTime now = LocalDateTime.now();
        int hours = windowHours <= 0 ? 24 : windowHours;
        LocalDateTime start = from != null ? from : now.minusHours(hours);
        LocalDateTime end = to != null ? to : now;
        return trendService.analyze(id, start, end, buckets);
    }

    /**
     * 下发效果分析：对比某条下发指令生效时刻前后各 windowMinutes 分钟的 effort 变化。
     * metric 默认 effort，windowMinutes 默认 30。
     */
    @GetMapping("/commands/{commandId}/effect")
    public PublishEffectReport commandEffect(
            @PathVariable Long commandId,
            @RequestParam(defaultValue = "effort") String metric,
            @RequestParam(defaultValue = "30") int windowMinutes) {
        return publishEffectService.evaluate(commandId, metric, windowMinutes);
    }
}
