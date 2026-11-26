package com.platform.robotcloud.experiment;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.platform.robotcloud.telemetry.TelemetryData;
import org.springframework.data.domain.Page;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
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

    private static final String EVENT_CSV_HEADER =
            "timestamp,run_id,event_type,sim_time_s,fault_type,joint_index,action,reason,reachability_status,detail";

    private final ExperimentService service;
    private final ObjectMapper mapper = new ObjectMapper();

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

    /** 按 run_id 导出可追溯材料：JSON 含 Run+事件，CSV 为事件时间线。 */
    @GetMapping("/{runId}/export")
    public ResponseEntity<byte[]> export(@PathVariable String runId,
                                         @RequestParam(defaultValue = "json") String format) {
        ExperimentRun run = service.require(runId);
        Map<String, Object> runView = service.runView(run);
        List<Map<String, Object>> events = service.events(runId).stream().map(service::eventView).toList();
        if ("csv".equalsIgnoreCase(format)) {
            StringBuilder csv = new StringBuilder(EVENT_CSV_HEADER).append('\n');
            for (Map<String, Object> event : events) {
                csv.append(csvCell(event.get("timestamp"))).append(',')
                        .append(csvCell(event.get("run_id"))).append(',')
                        .append(csvCell(event.get("event_type"))).append(',')
                        .append(csvCell(event.get("sim_time_s"))).append(',')
                        .append(csvCell(event.get("fault_type"))).append(',')
                        .append(csvCell(event.get("joint_index"))).append(',')
                        .append(csvCell(event.get("action"))).append(',')
                        .append(csvCell(event.get("reason"))).append(',')
                        .append(csvCell(event.get("reachability_status"))).append(',')
                        .append(csvCell(event.get("detail"))).append('\n');
            }
            return attachment(runId + "-events.csv", "text/csv;charset=UTF-8",
                    csv.toString().getBytes(StandardCharsets.UTF_8));
        }
        Map<String, Object> document = new LinkedHashMap<>();
        document.put("contract_version", runView.get("contract_version"));
        document.put("exported_at_ms", System.currentTimeMillis());
        document.put("run", runView);
        document.put("events", events);
        try {
            return attachment(runId + ".json", "application/json",
                    mapper.writeValueAsBytes(document));
        } catch (Exception e) {
            throw new IllegalStateException("export experiment run failed: " + runId, e);
        }
    }

    private static ResponseEntity<byte[]> attachment(String filename, String contentType, byte[] body) {
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + filename + "\"")
                .header(HttpHeaders.CONTENT_TYPE, contentType)
                .body(body);
    }

    private static String csvCell(Object value) {
        if (value == null) {
            return "";
        }
        String text = String.valueOf(value);
        if (text.indexOf(',') < 0 && text.indexOf('"') < 0
                && text.indexOf('\n') < 0 && text.indexOf('\r') < 0) {
            return text;
        }
        return '"' + text.replace("\"", "\"\"") + '"';
    }
}
