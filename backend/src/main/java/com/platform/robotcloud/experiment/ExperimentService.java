package com.platform.robotcloud.experiment;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.support.Payloads;
import com.platform.robotcloud.telemetry.TelemetryData;
import com.platform.robotcloud.telemetry.TelemetrySeriesService;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * V2 实验 Run/Event 的入库、查询与曲线窗口解析。
 */
@Service
public class ExperimentService {

    private static final int MAX_PAGE_SIZE = 100;
    private static final String RUN_ID_PATTERN = "^[0-9a-f]{32}$";

    private final ExperimentRunRepository runRepository;
    private final ExperimentEventRepository eventRepository;
    private final DeviceLookupService deviceLookupService;
    private final TelemetrySeriesService seriesService;
    private final ObjectMapper mapper = new ObjectMapper();

    public ExperimentService(ExperimentRunRepository runRepository,
                             ExperimentEventRepository eventRepository,
                             DeviceLookupService deviceLookupService,
                             TelemetrySeriesService seriesService) {
        this.runRepository = runRepository;
        this.eventRepository = eventRepository;
        this.deviceLookupService = deviceLookupService;
        this.seriesService = seriesService;
    }

    @Transactional
    public ExperimentRun ingestRun(JsonNode json) {
        String runId = Payloads.text(json, "run_id", null);
        if (runId == null || !runId.matches(RUN_ID_PATTERN)) {
            throw new IllegalArgumentException("experiment run has no valid run_id: " + runId);
        }
        JsonNode simulation = json.path("simulation");
        JsonNode scenario = json.path("scenario");
        JsonNode fault = json.path("fault");
        JsonNode reachability = json.path("reachability");
        JsonNode decision = json.path("decision");
        JsonNode task = json.path("task");
        JsonNode trace = json.path("trace");

        ExperimentRun run = runRepository.findByRunId(runId).orElseGet(ExperimentRun::new);
        LocalDateTime now = LocalDateTime.now();
        if (run.getId() == null) {
            run.setCreatedAt(now);
        }
        run.setRunId(runId);
        run.setContractVersion(Payloads.text(json, "contract_version", "2.0.0"));
        run.setAlgorithmVersion(Payloads.text(json, "algorithm_version", null));
        run.setSimulationId(Payloads.text(simulation, "simulation_id", null));
        run.setRobotId(Payloads.text(simulation, "robot_id", null));
        run.setScenarioId(Payloads.text(scenario, "scenario_id", null));
        run.setSplitName(Payloads.text(scenario, "split", null));
        run.setSeed(integerOrNull(scenario, "seed"));
        run.setStrategy(Payloads.text(json, "strategy", null));
        run.setStatus(Payloads.text(task, "status", "UNKNOWN"));

        long startedMs = json.path("started_at_ms").asLong(0L);
        LocalDateTime startedAt = startedMs > 0 ? Payloads.fromEpoch(startedMs) : now;
        double durationS = simulation.path("duration_s").asDouble(8.0);
        run.setStartedAt(startedAt);
        run.setWindowEndAt(startedAt.plusNanos((long) (Math.max(durationS, 0.1) * 1_000_000_000L)));

        run.setFaultType(Payloads.text(fault, "type", null));
        run.setFaultJoint(integerOrNull(fault, "joint_index"));
        run.setFaultInjectedAtS(doubleOrNull(fault, "injected_at_s"));
        run.setFaultDetectedAtS(doubleOrNull(fault, "detected_at_s"));
        run.setDetectionLatencyMs(doubleOrNull(fault, "detection_latency_ms"));
        run.setReachabilityStatus(Payloads.text(reachability, "status", null));
        run.setReachabilityReason(Payloads.text(reachability, "reason", null));
        run.setDecisionAction(Payloads.text(decision, "action", null));
        run.setDecisionReason(Payloads.text(decision, "reason", null));
        run.setDecisionAtS(doubleOrNull(decision, "at_s"));
        run.setFinalEeErrorM(doubleOrNull(task, "final_ee_error_m"));
        run.setRecoveryTimeS(doubleOrNull(task, "recovery_time_s"));
        run.setStopTimeS(doubleOrNull(task, "stop_time_s"));
        run.setPeakFaultJointTorqueNm(doubleOrNull(task, "peak_fault_joint_torque_nm"));
        run.setMaxJointSpeedRadS(doubleOrNull(task, "max_joint_speed_rad_s"));
        run.setMaxJointTorqueNm(doubleOrNull(task, "max_joint_torque_nm"));
        run.setTracePath(Payloads.text(trace, "path", null));
        run.setTraceSha256(Payloads.text(trace, "sha256", null));
        run.setPayload(json.toString());
        run.setUpdatedAt(now);

        String deviceCode = Payloads.text(simulation, "robot_id",
                Payloads.text(simulation, "simulation_id", "ROBOT-001"));
        run.setDeviceId(deviceLookupService.findOrCreateId(deviceCode));
        if (run.getSimulationId() != null) {
            deviceLookupService.bindSimulation(deviceCode, run.getSimulationId());
        }
        return runRepository.save(run);
    }

    @Transactional
    public void ingestEvent(JsonNode json) {
        String runId = Payloads.text(json, "run_id", null);
        if (runId == null) {
            throw new IllegalArgumentException("experiment event has no run_id");
        }
        String eventType = Payloads.text(json, "event_type", "EVENT").toUpperCase();
        long timestamp = json.path("timestamp").asLong(0L);
        if (timestamp <= 0) {
            timestamp = System.currentTimeMillis();
        }
        Integer joint = integerOrNull(json, "joint_index");
        String action = Payloads.text(json, "action", null);
        String eventKey = runId + "|" + eventType + "|" + timestamp + "|"
                + (joint == null ? "-" : joint) + "|" + (action == null ? "-" : action);
        if (eventRepository.existsByEventKey(eventKey)) {
            return;
        }
        ExperimentRun run = runRepository.findByRunId(runId)
                .orElseThrow(() -> new IllegalArgumentException("unknown run_id for event: " + runId));

        ExperimentEvent event = new ExperimentEvent();
        event.setEventKey(eventKey);
        event.setRunId(runId);
        event.setEventType(eventType);
        event.setEventTime(Payloads.fromEpoch(timestamp));
        event.setSimTimeS(doubleOrNull(json, "sim_time_s"));
        event.setFaultType(Payloads.text(json, "fault_type", null));
        event.setJointIndex(joint);
        event.setAction(action);
        event.setReason(Payloads.text(json, "reason", null));
        event.setReachabilityStatus(Payloads.text(json, "reachability_status", null));
        event.setDetail(Payloads.text(json, "detail", null));
        event.setPayload(json.toString());
        event.setCreatedAt(LocalDateTime.now());
        eventRepository.save(event);

        if ("DECISION".equals(eventType)) {
            run.setDecisionAction(action);
            run.setDecisionReason(event.getReason());
            if (event.getReachabilityStatus() != null) {
                run.setReachabilityStatus(event.getReachabilityStatus());
            }
            if (event.getSimTimeS() != null) {
                run.setDecisionAtS(event.getSimTimeS());
            }
            run.setUpdatedAt(LocalDateTime.now());
            runRepository.save(run);
        } else if ("FAULT".equals(eventType)) {
            run.setFaultType(event.getFaultType());
            run.setFaultJoint(event.getJointIndex());
            if (event.getSimTimeS() != null) {
                run.setFaultDetectedAtS(event.getSimTimeS());
            }
            run.setUpdatedAt(LocalDateTime.now());
            runRepository.save(run);
        }
    }

    public Page<ExperimentRun> page(int page, int size, Long deviceId, String status, String runId) {
        int safePage = Math.max(page, 0);
        int safeSize = Math.min(Math.max(size, 1), MAX_PAGE_SIZE);
        Pageable pageable = PageRequest.of(safePage, safeSize,
                Sort.by(Sort.Direction.DESC, "startedAt").and(Sort.by(Sort.Direction.DESC, "id")));
        Specification<ExperimentRun> spec = (root, query, cb) -> cb.conjunction();
        if (deviceId != null) {
            spec = spec.and((root, query, cb) -> cb.equal(root.get("deviceId"), deviceId));
        }
        if (status != null && !status.isBlank()) {
            String normalized = status.trim().toUpperCase();
            spec = spec.and((root, query, cb) -> cb.equal(root.get("status"), normalized));
        }
        if (runId != null && !runId.isBlank()) {
            String needle = "%" + runId.trim().toLowerCase() + "%";
            spec = spec.and((root, query, cb) -> cb.like(cb.lower(root.get("runId")), needle));
        }
        return runRepository.findAll(spec, pageable);
    }

    public ExperimentRun require(String runId) {
        return runRepository.findByRunId(runId)
                .orElseThrow(() -> new IllegalArgumentException("experiment run not found: " + runId));
    }

    public List<ExperimentEvent> events(String runId) {
        return eventRepository.findByRunIdOrderByEventTimeAscIdAsc(runId);
    }

    public List<TelemetryData> series(String runId, int limit, boolean downsample) {
        ExperimentRun run = require(runId);
        LocalDateTime from = run.getStartedAt();
        LocalDateTime to = run.getWindowEndAt();
        if (from == null) {
            from = LocalDateTime.now().minusSeconds(8);
        }
        if (to == null) {
            to = from.plusSeconds(8);
        }
        Long deviceId = run.getDeviceId();
        if (deviceId == null) {
            return List.of();
        }
        return seriesService.series(deviceId, from, to, Math.min(Math.max(limit, 1), 2000), downsample);
    }

    public Map<String, Object> runView(ExperimentRun run) {
        Map<String, Object> map = new LinkedHashMap<>();
        if (run.getPayload() != null) {
            try {
                map.putAll(mapper.readValue(run.getPayload(),
                        new TypeReference<LinkedHashMap<String, Object>>() { }));
            } catch (Exception ignored) {
                // 坏 JSON 时退回列字段，至少列表/详情可用
            }
        }
        map.putIfAbsent("run_id", run.getRunId());
        map.putIfAbsent("contract_version", run.getContractVersion());
        map.putIfAbsent("algorithm_version", run.getAlgorithmVersion());
        map.putIfAbsent("strategy", run.getStrategy());
        // 实时 Run 的 payload 在启动时写入，后续事件只更新索引列；这里把列值回填到响应，
        // 保证按 run_id 查询时能看到最新故障/决策/状态。
        Map<String, Object> fault = asMap(map.get("fault"));
        putIfNotNull(fault, "type", run.getFaultType());
        putIfNotNull(fault, "joint_index", run.getFaultJoint());
        putIfNotNull(fault, "joint_name", run.getFaultJoint() == null ? null : "J" + run.getFaultJoint());
        putIfNotNull(fault, "detected_at_s", run.getFaultDetectedAtS());
        putIfNotNull(fault, "detection_latency_ms", run.getDetectionLatencyMs());
        if (run.getFaultType() != null) {
            fault.put("confirmed", true);
        }
        map.put("fault", fault);

        Map<String, Object> reachability = asMap(map.get("reachability"));
        putIfNotNull(reachability, "status", run.getReachabilityStatus());
        putIfNotNull(reachability, "reason", run.getReachabilityReason());
        map.put("reachability", reachability);

        Map<String, Object> decision = asMap(map.get("decision"));
        putIfNotNull(decision, "action", run.getDecisionAction());
        putIfNotNull(decision, "reason", run.getDecisionReason());
        putIfNotNull(decision, "at_s", run.getDecisionAtS());
        map.put("decision", decision);

        Map<String, Object> task = asMap(map.get("task"));
        putIfNotNull(task, "status", run.getStatus());
        putIfNotNull(task, "final_ee_error_m", run.getFinalEeErrorM());
        putIfNotNull(task, "recovery_time_s", run.getRecoveryTimeS());
        putIfNotNull(task, "stop_time_s", run.getStopTimeS());
        putIfNotNull(task, "peak_fault_joint_torque_nm", run.getPeakFaultJointTorqueNm());
        putIfNotNull(task, "max_joint_speed_rad_s", run.getMaxJointSpeedRadS());
        putIfNotNull(task, "max_joint_torque_nm", run.getMaxJointTorqueNm());
        map.put("task", task);

        map.put("device_id", run.getDeviceId());
        map.put("updated_at_ms", run.getUpdatedAt() == null ? null
                : run.getUpdatedAt().atZone(Payloads.PLATFORM_ZONE).toInstant().toEpochMilli());
        return map;
    }

    public Map<String, Object> eventView(ExperimentEvent event) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("run_id", event.getRunId());
        map.put("event_type", event.getEventType());
        map.put("timestamp", event.getEventTime().atZone(Payloads.PLATFORM_ZONE).toInstant().toEpochMilli());
        map.put("sim_time_s", event.getSimTimeS());
        map.put("fault_type", event.getFaultType());
        map.put("joint_index", event.getJointIndex());
        map.put("action", event.getAction());
        map.put("reason", event.getReason());
        map.put("reachability_status", event.getReachabilityStatus());
        map.put("detail", event.getDetail());
        return map;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object value) {
        if (value instanceof Map<?, ?> existing) {
            return (Map<String, Object>) existing;
        }
        return new LinkedHashMap<>();
    }

    private static void putIfNotNull(Map<String, Object> target, String key, Object value) {
        if (value != null) {
            target.put(key, value);
        }
    }

    private static Integer integerOrNull(JsonNode json, String field) {        JsonNode node = json.path(field);
        return node.isNumber() ? node.asInt() : null;
    }

    private static Double doubleOrNull(JsonNode json, String field) {
        JsonNode node = json.path(field);
        return node.isNumber() ? node.asDouble() : null;
    }
}
