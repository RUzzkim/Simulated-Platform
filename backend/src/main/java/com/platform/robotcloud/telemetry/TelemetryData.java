package com.platform.robotcloud.telemetry;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "telemetry_data")
public class TelemetryData {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id", nullable = false)
    private Long deviceId;

    @Column(name = "reported_at", nullable = false)
    private LocalDateTime reportedAt;

    private String state;

    @Column(name = "control_mode")
    private String controlMode;

    @Column(name = "joint_payload", nullable = false, columnDefinition = "json")
    private String jointPayload;

    @Column(name = "end_effector_payload", columnDefinition = "json")
    private String endEffectorPayload;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
    public LocalDateTime getReportedAt() { return reportedAt; }
    public void setReportedAt(LocalDateTime reportedAt) { this.reportedAt = reportedAt; }
    public String getState() { return state; }
    public void setState(String state) { this.state = state; }
    public String getControlMode() { return controlMode; }
    public void setControlMode(String controlMode) { this.controlMode = controlMode; }
    public String getJointPayload() { return jointPayload; }
    public void setJointPayload(String jointPayload) { this.jointPayload = jointPayload; }
    public String getEndEffectorPayload() { return endEffectorPayload; }
    public void setEndEffectorPayload(String endEffectorPayload) { this.endEffectorPayload = endEffectorPayload; }
}

