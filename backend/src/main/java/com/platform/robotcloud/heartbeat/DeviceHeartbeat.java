package com.platform.robotcloud.heartbeat;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "device_heartbeat")
public class DeviceHeartbeat {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id", nullable = false)
    private Long deviceId;

    @Column(nullable = false)
    private String status;

    @Column(name = "cpu_usage")
    private BigDecimal cpuUsage;

    @Column(name = "memory_usage")
    private BigDecimal memoryUsage;

    @Column(name = "edge_version")
    private String edgeVersion;

    @Column(name = "reported_at", nullable = false)
    private LocalDateTime reportedAt;

    public Long getId() { return id; }
    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public BigDecimal getCpuUsage() { return cpuUsage; }
    public void setCpuUsage(BigDecimal cpuUsage) { this.cpuUsage = cpuUsage; }
    public BigDecimal getMemoryUsage() { return memoryUsage; }
    public void setMemoryUsage(BigDecimal memoryUsage) { this.memoryUsage = memoryUsage; }
    public String getEdgeVersion() { return edgeVersion; }
    public void setEdgeVersion(String edgeVersion) { this.edgeVersion = edgeVersion; }
    public LocalDateTime getReportedAt() { return reportedAt; }
    public void setReportedAt(LocalDateTime reportedAt) { this.reportedAt = reportedAt; }
}