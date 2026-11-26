package com.platform.robotcloud.experiment;

import com.platform.robotcloud.telemetry.TelemetryData;
import org.springframework.data.domain.Page;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * V2 实验记录查询：列表、详情、故障/决策事件、曲线。
 * <p>响应字段与 docs/v2-experiment-contract.md 的 2.0.0 契约一致（snake_case）。
 */
@RestController
@RequestMapping("/api/experiments/runs")
public class ExperimentController {

    private final ExperimentService service;

    public ExperimentController(ExperimentService service) {
        this.service = service;
    }

    @GetMapping
    public Map<String, Object> list(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) Long deviceId,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String runId) {
        Page<ExperimentRun> result = service.page(page, size, deviceId, status, runId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("items", result.getContent().stream().map(service::runView).toList());
        body.put("total", result.getTotalElements());
        body.put("page", result.getNumber());
        body.put("size", result.getSize());
        return body;
    }

    @GetMapping("/{runId}")
    public Map<String, Object> detail(@PathVariable String runId) {
        return service.runView(service.require(runId));
    }

    @GetMapping("/{runId}/events")
    public List<Map<String, Object>> events(@PathVariable String runId) {
        service.require(runId);
        return service.events(runId).stream().map(service::eventView).toList();
    }

    @GetMapping("/{runId}/series")
    public List<TelemetryData> series(
            @PathVariable String runId,
            @RequestParam(defaultValue = "800") int limit,
            @RequestParam(defaultValue = "false") boolean downsample) {
        return service.series(runId, limit, downsample);
    }
}
