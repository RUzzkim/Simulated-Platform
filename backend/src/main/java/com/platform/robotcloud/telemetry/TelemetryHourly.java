package com.platform.robotcloud.telemetry;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 遥测归档：明细超过保留期后按小时聚合成一行，只保留均值与帧数，供长期趋势查询。
 */
@Entity
@Table(name = "telemetry_hourly")
public class TelemetryHourly {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id", nullable = false)
    private Long deviceId;

    @Column(name = "bucket_start", nullable = false)
    private LocalDateTime bucketStart;

    @Column(name = "frame_count", nullable = false)
    private Integer frameCount;

    private String state;

    @Column(name = "control_mode")
    private String controlMode;

    @Column(name = "joint_metrics", nullable = false, columnDefinition = "json")
    private String jointMetrics;

    @Column(name = "archived_at", nullable = false)
    private LocalDateTime archivedAt;

    public Long getId() { return id; }
    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
    public LocalDateTime getBucketStart() { return bucketStart; }
    public void setBucketStart(LocalDateTime bucketStart) { this.bucketStart = bucketStart; }
    public Integer getFrameCount() { return frameCount; }
    public void setFrameCount(Integer frameCount) { this.frameCount = frameCount; }
    public String getState() { return state; }
    public void setState(String state) { this.state = state; }
    public String getControlMode() { return controlMode; }
    public void setControlMode(String controlMode) { this.controlMode = controlMode; }
    public String getJointMetrics() { return jointMetrics; }
    public void setJointMetrics(String jointMetrics) { this.jointMetrics = jointMetrics; }
    public LocalDateTime getArchivedAt() { return archivedAt; }
    public void setArchivedAt(LocalDateTime archivedAt) { this.archivedAt = archivedAt; }
}