package com.platform.robotcloud.credential;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 每台设备的接入凭据：MQTT 账号（明文密码用 AES-GCM 加密存 secret_cipher）+ edge token 版本号。
 * token_version 递增即让此前签发的 edge token 立即失效（轮换/吊销）。
 */
@Entity
@Table(name = "device_credential")
public class DeviceCredential {

    public static final String STATUS_ACTIVE = "ACTIVE";
    public static final String STATUS_REVOKED = "REVOKED";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id", nullable = false, unique = true)
    private Long deviceId;

    @Column(name = "mqtt_username", nullable = false, unique = true)
    private String mqttUsername;

    @Column(name = "secret_cipher", nullable = false, columnDefinition = "text")
    private String secretCipher;

    @Column(name = "token_cipher", nullable = false, columnDefinition = "text")
    private String tokenCipher;

    @Column(name = "token_version", nullable = false)
    private int tokenVersion = 1;

    @Column(nullable = false)
    private String status = STATUS_ACTIVE;

    @Column(name = "issued_by")
    private Long issuedBy;

    @Column(name = "issued_at", nullable = false)
    private LocalDateTime issuedAt;

    @Column(name = "rotated_at")
    private LocalDateTime rotatedAt;

    @Column(name = "revoked_at")
    private LocalDateTime revokedAt;

    public Long getId() { return id; }
    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
    public String getMqttUsername() { return mqttUsername; }
    public void setMqttUsername(String mqttUsername) { this.mqttUsername = mqttUsername; }
    public String getSecretCipher() { return secretCipher; }
    public void setSecretCipher(String secretCipher) { this.secretCipher = secretCipher; }
    public String getTokenCipher() { return tokenCipher; }
    public void setTokenCipher(String tokenCipher) { this.tokenCipher = tokenCipher; }
    public int getTokenVersion() { return tokenVersion; }
    public void setTokenVersion(int tokenVersion) { this.tokenVersion = tokenVersion; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Long getIssuedBy() { return issuedBy; }
    public void setIssuedBy(Long issuedBy) { this.issuedBy = issuedBy; }
    public LocalDateTime getIssuedAt() { return issuedAt; }
    public void setIssuedAt(LocalDateTime issuedAt) { this.issuedAt = issuedAt; }
    public LocalDateTime getRotatedAt() { return rotatedAt; }
    public void setRotatedAt(LocalDateTime rotatedAt) { this.rotatedAt = rotatedAt; }
    public LocalDateTime getRevokedAt() { return revokedAt; }
    public void setRevokedAt(LocalDateTime revokedAt) { this.revokedAt = revokedAt; }
}