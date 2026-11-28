package com.platform.robotcloud.experiment;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * V2 实验运行（契约 2.0.0 的 Run 记录）。
 * <p>payload 保存规范化后的完整契约 JSON，索引列只用于列表过滤和快速展示。
 */
@Entity
@Table(name = "experiment_run")
public class ExperimentRun {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "run_id", nullable = false, unique = true, length = 32)
    private String runId;

    @Column(name = "device_id")
    private Long deviceId;

    @Column(name = "simulation_id", length = 16)
    private String simulationId;

    @Column(name = "robot_id", length = 32)
    private String robotId;

    @Column(name = "contract_version", length = 16)
    private String contractVersion;

    @Column(name = "algorithm_version", length = 32)
    private String algorithmVersion;

    @Column(name = "scenario_id", length = 96)
    private String scenarioId;

    @Column(name = "split_name", length = 32)
    private String splitName;

    private Integer seed;

    @Column(length = 16)
    private String strategy;

    @Column(length = 32)
    private String status;

    @Column(name = "started_at")
    private LocalDateTime startedAt;

    @Column(name = "window_end_at")
    private LocalDateTime windowEndAt;

    @Column(name = "fault_type", length = 32)
    private String faultType;

    @Column(name = "fault_joint")
    private Integer faultJoint;

    @Column(name = "fault_injected_at_s")
    private Double faultInjectedAtS;

    @Column(name = "fault_detected_at_s")
    private Double faultDetectedAtS;

    @Column(name = "detection_latency_ms")
    private Double detectionLatencyMs;

    @Column(name = "reachability_status", length = 32)
    private String reachabilityStatus;

    @Column(name = "reachability_reason", length = 64)
    private String reachabilityReason;

    @Column(name = "decision_action", length = 16)
    private String decisionAction;

    @Column(name = "decision_reason", length = 64)
    private String decisionReason;

    @Column(name = "decision_at_s")
    private Double decisionAtS;

    @Column(name = "final_ee_error_m")
    private Double finalEeErrorM;

    @Column(name = "recovery_time_s")
    private Double recoveryTimeS;

    @Column(name = "stop_time_s")
    private Double stopTimeS;

    @Column(name = "peak_fault_joint_torque_nm")
    private Double peakFaultJointTorqueNm;

    @Column(name = "max_joint_speed_rad_s")
    private Double maxJointSpeedRadS;

    @Column(name = "max_joint_torque_nm")
    private Double maxJointTorqueNm;

    @Column(name = "trace_path", length = 512)
    private String tracePath;

    @Column(name = "trace_sha256", length = 64)
    private String traceSha256;

    @Column(columnDefinition = "json")
    private String payload;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getRunId() { return runId; }
    public void setRunId(String runId) { this.runId = runId; }
    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
    public String getSimulationId() { return simulationId; }
    public void setSimulationId(String simulationId) { this.simulationId = simulationId; }
    public String getRobotId() { return robotId; }
    public void setRobotId(String robotId) { this.robotId = robotId; }
    public String getContractVersion() { return contractVersion; }
    public void setContractVersion(String contractVersion) { this.contractVersion = contractVersion; }
    public String getAlgorithmVersion() { return algorithmVersion; }
    public void setAlgorithmVersion(String algorithmVersion) { this.algorithmVersion = algorithmVersion; }
    public String getScenarioId() { return scenarioId; }
    public void setScenarioId(String scenarioId) { this.scenarioId = scenarioId; }
    public String getSplitName() { return splitName; }
    public void setSplitName(String splitName) { this.splitName = splitName; }
    public Integer getSeed() { return seed; }
    public void setSeed(Integer seed) { this.seed = seed; }
    public String getStrategy() { return strategy; }
    public void setStrategy(String strategy) { this.strategy = strategy; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public LocalDateTime getStartedAt() { return startedAt; }
    public void setStartedAt(LocalDateTime startedAt) { this.startedAt = startedAt; }
    public LocalDateTime getWindowEndAt() { return windowEndAt; }
    public void setWindowEndAt(LocalDateTime windowEndAt) { this.windowEndAt = windowEndAt; }
    public String getFaultType() { return faultType; }
    public void setFaultType(String faultType) { this.faultType = faultType; }
    public Integer getFaultJoint() { return faultJoint; }
    public void setFaultJoint(Integer faultJoint) { this.faultJoint = faultJoint; }
    public Double getFaultInjectedAtS() { return faultInjectedAtS; }
    public void setFaultInjectedAtS(Double faultInjectedAtS) { this.faultInjectedAtS = faultInjectedAtS; }
    public Double getFaultDetectedAtS() { return faultDetectedAtS; }
    public void setFaultDetectedAtS(Double faultDetectedAtS) { this.faultDetectedAtS = faultDetectedAtS; }
    public Double getDetectionLatencyMs() { return detectionLatencyMs; }
    public void setDetectionLatencyMs(Double detectionLatencyMs) { this.detectionLatencyMs = detectionLatencyMs; }
    public String getReachabilityStatus() { return reachabilityStatus; }
    public void setReachabilityStatus(String reachabilityStatus) { this.reachabilityStatus = reachabilityStatus; }
    public String getReachabilityReason() { return reachabilityReason; }
    public void setReachabilityReason(String reachabilityReason) { this.reachabilityReason = reachabilityReason; }
    public String getDecisionAction() { return decisionAction; }
    public void setDecisionAction(String decisionAction) { this.decisionAction = decisionAction; }
    public String getDecisionReason() { return decisionReason; }
    public void setDecisionReason(String decisionReason) { this.decisionReason = decisionReason; }
    public Double getDecisionAtS() { return decisionAtS; }
    public void setDecisionAtS(Double decisionAtS) { this.decisionAtS = decisionAtS; }
    public Double getFinalEeErrorM() { return finalEeErrorM; }
    public void setFinalEeErrorM(Double finalEeErrorM) { this.finalEeErrorM = finalEeErrorM; }
    public Double getRecoveryTimeS() { return recoveryTimeS; }
    public void setRecoveryTimeS(Double recoveryTimeS) { this.recoveryTimeS = recoveryTimeS; }
    public Double getStopTimeS() { return stopTimeS; }
    public void setStopTimeS(Double stopTimeS) { this.stopTimeS = stopTimeS; }
    public Double getPeakFaultJointTorqueNm() { return peakFaultJointTorqueNm; }
    public void setPeakFaultJointTorqueNm(Double peakFaultJointTorqueNm) { this.peakFaultJointTorqueNm = peakFaultJointTorqueNm; }
    public Double getMaxJointSpeedRadS() { return maxJointSpeedRadS; }
    public void setMaxJointSpeedRadS(Double maxJointSpeedRadS) { this.maxJointSpeedRadS = maxJointSpeedRadS; }
    public Double getMaxJointTorqueNm() { return maxJointTorqueNm; }
    public void setMaxJointTorqueNm(Double maxJointTorqueNm) { this.maxJointTorqueNm = maxJointTorqueNm; }
    public String getTracePath() { return tracePath; }
    public void setTracePath(String tracePath) { this.tracePath = tracePath; }
    public String getTraceSha256() { return traceSha256; }
    public void setTraceSha256(String traceSha256) { this.traceSha256 = traceSha256; }
    public String getPayload() { return payload; }
    public void setPayload(String payload) { this.payload = payload; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
