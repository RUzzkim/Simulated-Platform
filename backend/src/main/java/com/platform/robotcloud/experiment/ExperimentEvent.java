package com.platform.robotcloud.experiment;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * V2 实验事件（FAULT/DECISION），按 run_id 与 {@link ExperimentRun} 关联。
 */
@Entity
@Table(name = "experiment_event")
public class ExperimentEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** run_id|event_type|timestamp|joint|action，用于幂等重放。 */
    @Column(name = "event_key", nullable = false, unique = true, length = 160)
    private String eventKey;

    @Column(name = "run_id", nullable = false, length = 32)
    private String runId;

    @Column(name = "event_type", nullable = false, length = 16)
    private String eventType;

    @Column(name = "event_time", nullable = false)
    private LocalDateTime eventTime;

    @Column(name = "sim_time_s")
    private Double simTimeS;

    @Column(name = "fault_type", length = 32)
    private String faultType;

    @Column(name = "joint_index")
    private Integer jointIndex;

    @Column(length = 16)
    private String action;

    @Column(length = 64)
    private String reason;

    @Column(name = "reachability_status", length = 32)
    private String reachabilityStatus;

    @Column(columnDefinition = "text")
    private String detail;

    @Column(columnDefinition = "json")
    private String payload;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getEventKey() { return eventKey; }
    public void setEventKey(String eventKey) { this.eventKey = eventKey; }
    public String getRunId() { return runId; }
    public void setRunId(String runId) { this.runId = runId; }
    public String getEventType() { return eventType; }
    public void setEventType(String eventType) { this.eventType = eventType; }
    public LocalDateTime getEventTime() { return eventTime; }
    public void setEventTime(LocalDateTime eventTime) { this.eventTime = eventTime; }
    public Double getSimTimeS() { return simTimeS; }
    public void setSimTimeS(Double simTimeS) { this.simTimeS = simTimeS; }
    public String getFaultType() { return faultType; }
    public void setFaultType(String faultType) { this.faultType = faultType; }
    public Integer getJointIndex() { return jointIndex; }
    public void setJointIndex(Integer jointIndex) { this.jointIndex = jointIndex; }
    public String getAction() { return action; }
    public void setAction(String action) { this.action = action; }
    public String getReason() { return reason; }
    public void setReason(String reason) { this.reason = reason; }
    public String getReachabilityStatus() { return reachabilityStatus; }
    public void setReachabilityStatus(String reachabilityStatus) { this.reachabilityStatus = reachabilityStatus; }
    public String getDetail() { return detail; }
    public void setDetail(String detail) { this.detail = detail; }
    public String getPayload() { return payload; }
    public void setPayload(String payload) { this.payload = payload; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
