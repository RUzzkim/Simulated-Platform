package com.platform.robotcloud.command;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "command_log")
public class CommandLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id", nullable = false)
    private Long deviceId;

    /** simulation 契约专用：仿真实例编号（SIM-001）；robot 契约设备为 null。 */
    @Column(name = "simulation_id", length = 32)
    private String simulationId;

    /** simulation 契约专用：指令报文里的 robotId（ROBOT-001），设备改名后仍可追溯。 */
    @Column(name = "target_robot_id", length = 64)
    private String targetRobotId;

    @Column(name = "message_id", nullable = false, unique = true)
    private String messageId;

    @Column(name = "cmd_type", nullable = false)
    private String cmdType;

    private Integer version;

    @Column(nullable = false, columnDefinition = "json")
    private String payload;

    @Column(name = "issued_by")
    private Long issuedBy;

    @Column(name = "issued_by_name")
    private String issuedByName;

    @Column(name = "issued_at", nullable = false)
    private LocalDateTime issuedAt;

    private String result;

    @Column(name = "result_detail")
    private String resultDetail;

    @Column(name = "acknowledged_at")
    private LocalDateTime acknowledgedAt;

    public Long getId() { return id; }
    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
    public String getSimulationId() { return simulationId; }
    public void setSimulationId(String simulationId) { this.simulationId = simulationId; }
    public String getTargetRobotId() { return targetRobotId; }
    public void setTargetRobotId(String targetRobotId) { this.targetRobotId = targetRobotId; }
    public String getMessageId() { return messageId; }
    public void setMessageId(String messageId) { this.messageId = messageId; }
    public String getCmdType() { return cmdType; }
    public void setCmdType(String cmdType) { this.cmdType = cmdType; }
    public Integer getVersion() { return version; }
    public void setVersion(Integer version) { this.version = version; }
    public String getPayload() { return payload; }
    public void setPayload(String payload) { this.payload = payload; }
    public Long getIssuedBy() { return issuedBy; }
    public void setIssuedBy(Long issuedBy) { this.issuedBy = issuedBy; }
    public String getIssuedByName() { return issuedByName; }
    public void setIssuedByName(String issuedByName) { this.issuedByName = issuedByName; }
    public LocalDateTime getIssuedAt() { return issuedAt; }
    public void setIssuedAt(LocalDateTime issuedAt) { this.issuedAt = issuedAt; }
    public String getResult() { return result; }
    public void setResult(String result) { this.result = result; }
    public String getResultDetail() { return resultDetail; }
    public void setResultDetail(String resultDetail) { this.resultDetail = resultDetail; }
    public LocalDateTime getAcknowledgedAt() { return acknowledgedAt; }
    public void setAcknowledgedAt(LocalDateTime acknowledgedAt) { this.acknowledgedAt = acknowledgedAt; }
}