package com.platform.robotcloud.event;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "fault_event")
public class FaultEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id", nullable = false)
    private Long deviceId;

    @Column(name = "event_type", nullable = false)
    private String eventType;

    @Column(nullable = false)
    private String level;

    private String detail;

    @Column(name = "context_payload", columnDefinition = "json")
    private String contextPayload;

    @Column(name = "occurred_at", nullable = false)
    private LocalDateTime occurredAt;

    public Long getId() { return id; }
    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
    public String getEventType() { return eventType; }
    public void setEventType(String eventType) { this.eventType = eventType; }
    public String getLevel() { return level; }
    public void setLevel(String level) { this.level = level; }
    public String getDetail() { return detail; }
    public void setDetail(String detail) { this.detail = detail; }
    public String getContextPayload() { return contextPayload; }
    public void setContextPayload(String contextPayload) { this.contextPayload = contextPayload; }
    public LocalDateTime getOccurredAt() { return occurredAt; }
    public void setOccurredAt(LocalDateTime occurredAt) { this.occurredAt = occurredAt; }
}