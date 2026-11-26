package com.platform.robotcloud.experiment;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.telemetry.TelemetrySeriesService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 契约 2.0.0 的 Run/Event 入库规则。
 * 实时边端会重复上报同一 run_id 的部分 Run（IN_PROGRESS → INCOMPLETE），
 * 后到的快照不能清空由事件写入的 fault/decision/reachability 索引列。
 */
class ExperimentServiceIngestTest {

    private static final String RUN_ID = "0123456789abcdef0123456789abcdef";

    private final ObjectMapper mapper = new ObjectMapper();
    private ExperimentRunRepository runRepository;
    private ExperimentEventRepository eventRepository;
    private ExperimentService service;

    @BeforeEach
    void setUp() {
        runRepository = mock(ExperimentRunRepository.class);
        eventRepository = mock(ExperimentEventRepository.class);
        DeviceLookupService devices = mock(DeviceLookupService.class);
        when(devices.findOrCreateId(anyString())).thenReturn(1L);
        when(runRepository.save(any(ExperimentRun.class))).thenAnswer(call -> call.getArgument(0));
        when(eventRepository.save(any(ExperimentEvent.class))).thenAnswer(call -> call.getArgument(0));
        service = new ExperimentService(runRepository, eventRepository, devices,
                mock(TelemetrySeriesService.class));
    }

    @Test
    void incompleteSnapshotKeepsColumnsWrittenByEvents() throws Exception {
        ExperimentRun existing = existingRun("IN_PROGRESS");
        existing.setFaultType("JOINT_LOCKED");
        existing.setFaultJoint(0);
        existing.setFaultDetectedAtS(2.107);
        existing.setReachabilityStatus("REACHABLE");
        existing.setReachabilityReason("TARGET_REACHED");
        existing.setDecisionAction("RECOVER");
        existing.setDecisionReason("TARGET_REACHED");
        existing.setDecisionAtS(2.172);
        when(runRepository.findByRunId(RUN_ID)).thenReturn(Optional.of(existing));

        ExperimentRun saved = service.ingestRun(snapshot("INCOMPLETE"));

        assertEquals("INCOMPLETE", saved.getStatus());
        assertEquals("JOINT_LOCKED", saved.getFaultType());
        assertEquals(Integer.valueOf(0), saved.getFaultJoint());
        assertEquals(2.107, saved.getFaultDetectedAtS(), 1e-9);
        assertEquals("REACHABLE", saved.getReachabilityStatus());
        assertEquals("RECOVER", saved.getDecisionAction());
        assertEquals("TARGET_REACHED", saved.getDecisionReason());
        assertEquals(2.172, saved.getDecisionAtS(), 1e-9);
    }

    @Test
    void firstLiveSnapshotStillRecordsNotAssessed() throws Exception {
        when(runRepository.findByRunId(RUN_ID)).thenReturn(Optional.of(new ExperimentRun()));

        ExperimentRun saved = service.ingestRun(snapshot("IN_PROGRESS"));

        assertEquals("IN_PROGRESS", saved.getStatus());
        assertEquals("NOT_ASSESSED", saved.getReachabilityStatus());
        assertNull(saved.getFaultType());
        assertNull(saved.getDecisionAction());
    }

    @Test
    void completedRunSnapshotOverwritesIndexColumns() throws Exception {
        ExperimentRun existing = existingRun("IN_PROGRESS");
        existing.setFaultType("JOINT_LOCKED");
        existing.setFaultJoint(0);
        existing.setReachabilityStatus("REACHABLE");
        existing.setDecisionAction("RECOVER");
        when(runRepository.findByRunId(RUN_ID)).thenReturn(Optional.of(existing));

        ExperimentRun saved = service.ingestRun(snapshot("RECOVERED"));

        assertEquals("RECOVERED", saved.getStatus());
        assertNull(saved.getFaultType());
        assertNull(saved.getFaultJoint());
        assertEquals("NOT_ASSESSED", saved.getReachabilityStatus());
        assertNull(saved.getDecisionAction());
    }

    @Test
    void faultEventFillsFaultIndexColumns() throws Exception {
        ExperimentRun existing = existingRun("IN_PROGRESS");
        when(runRepository.findByRunId(RUN_ID)).thenReturn(Optional.of(existing));
        when(eventRepository.existsByEventKey(anyString())).thenReturn(false);

        service.ingestEvent(event("FAULT",
                "\"fault_type\":\"JOINT_LOCKED\",\"joint_index\":0,\"sim_time_s\":2.107,"));

        assertEquals("JOINT_LOCKED", existing.getFaultType());
        assertEquals(Integer.valueOf(0), existing.getFaultJoint());
        assertEquals(2.107, existing.getFaultDetectedAtS(), 1e-9);
        verify(eventRepository).save(any(ExperimentEvent.class));
    }

    @Test
    void decisionEventFillsDecisionAndReachability() throws Exception {
        ExperimentRun existing = existingRun("IN_PROGRESS");
        when(runRepository.findByRunId(RUN_ID)).thenReturn(Optional.of(existing));
        when(eventRepository.existsByEventKey(anyString())).thenReturn(false);

        service.ingestEvent(event("DECISION",
                "\"action\":\"RECOVER\",\"reason\":\"TARGET_REACHED\","
                        + "\"reachability_status\":\"REACHABLE\",\"sim_time_s\":2.172,"));

        assertEquals("RECOVER", existing.getDecisionAction());
        assertEquals("TARGET_REACHED", existing.getDecisionReason());
        assertEquals("REACHABLE", existing.getReachabilityStatus());
        assertEquals(2.172, existing.getDecisionAtS(), 1e-9);
    }

    @Test
    void duplicateEventIsIgnored() throws Exception {
        when(eventRepository.existsByEventKey(anyString())).thenReturn(true);

        service.ingestEvent(event("DECISION", "\"action\":\"RECOVER\","));

        verify(eventRepository, never()).save(any(ExperimentEvent.class));
        verify(runRepository, never()).save(any(ExperimentRun.class));
    }

    private ExperimentRun existingRun(String status) {
        ExperimentRun run = new ExperimentRun();
        run.setId(1L);
        run.setRunId(RUN_ID);
        run.setStatus(status);
        run.setCreatedAt(LocalDateTime.now());
        return run;
    }

    private JsonNode snapshot(String status) throws Exception {
        return mapper.readTree("""
                {
                  "contract_version": "2.0.0",
                  "run_id": "%s",
                  "started_at_ms": 1760000000000,
                  "simulation": {"simulation_id": "SIM-001", "robot_id": "ROBOT-001",
                                 "plant": "python-6r", "duration_s": 8.0},
                  "scenario": {"scenario_id": "ONLINE-DECISION", "split": "online", "seed": 300},
                  "fault": {"type": null, "joint_index": null},
                  "reachability": {"status": "NOT_ASSESSED", "reason": null},
                  "decision": {"action": null, "reason": null, "at_s": null},
                  "strategy": "v2",
                  "task": {"status": "%s"},
                  "trace": {"path": "live://%s", "sha256": "%s", "frame_count": 1}
                }
                """.formatted(RUN_ID, status, RUN_ID, "0".repeat(64)));
    }

    private JsonNode event(String type, String extraFields) throws Exception {
        return mapper.readTree("""
                {"run_id": "%s", "event_type": "%s", "timestamp": 1760000002000, %s
                 "detail": "test"}
                """.formatted(RUN_ID, type, extraFields));
    }
}
