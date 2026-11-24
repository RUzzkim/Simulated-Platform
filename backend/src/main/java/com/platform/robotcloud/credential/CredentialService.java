package com.platform.robotcloud.credential;

import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import com.platform.robotcloud.device.Device;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.security.CurrentUserService;
import com.platform.robotcloud.security.EdgeTokenValidator;
import com.platform.robotcloud.security.JwtService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Base64;
import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 设备接入凭据（对接边/端）：
 * - MQTT 账号只允许发布自己的 telemetry/heartbeat/event/cmd_ack，订阅自己的 cmd；
 * - edge token 用于 HTTP 上报通道 /api/edge/**，轮换或吊销后旧令牌立即失效。
 * 明文密码与令牌都用 SecretCipher 加密存储，运维可随时在详情页查看，不需要重新签发。
 */
@Service
public class CredentialService implements EdgeTokenValidator {

    private static final Pattern SAFE_USERNAME = Pattern.compile("[^A-Za-z0-9_.-]");
    private static final int SECRET_BYTES = 18;

    private final DeviceCredentialRepository repository;
    private final DeviceLookupService deviceLookupService;
    private final SecretCipher cipher;
    private final JwtService jwtService;
    private final AuditService auditService;
    private final String brokerHost;
    private final int brokerPort;

    public CredentialService(DeviceCredentialRepository repository,
                             DeviceLookupService deviceLookupService,
                             SecretCipher cipher,
                             JwtService jwtService,
                             AuditService auditService,
                             @Value("${app.edge.broker-host:localhost}") String brokerHost,
                             @Value("${app.edge.broker-port:8883}") int brokerPort) {
        this.repository = repository;
        this.deviceLookupService = deviceLookupService;
        this.cipher = cipher;
        this.jwtService = jwtService;
        this.auditService = auditService;
        this.brokerHost = brokerHost;
        this.brokerPort = brokerPort;
    }

    public record CredentialView(Long deviceId,
                                 String deviceCode,
                                 String deviceName,
                                 String status,
                                 String mqttUsername,
                                 String mqttPassword,
                                 String edgeToken,
                                 String tokenExpiresAt,
                                 String brokerHost,
                                 int brokerPort,
                                 List<String> subscribeTopics,
                                 List<String> publishTopics,
                                 LocalDateTime issuedAt,
                                 LocalDateTime rotatedAt) {
    }

    /** 签发或轮换：token_version 递增，让旧 edge token 立刻失效。 */
    public CredentialView issue(Long deviceId) {
        Device device = deviceLookupService.requireDevice(deviceId);
        DeviceCredential credential = repository.findByDeviceId(deviceId).orElseGet(DeviceCredential::new);
        boolean rotation = credential.getId() != null;

        String password = randomSecret();
        credential.setDeviceId(deviceId);
        credential.setMqttUsername(mqttUsername(device, credential));
        credential.setSecretCipher(cipher.encrypt(password));
        credential.setTokenVersion(rotation ? credential.getTokenVersion() + 1 : 1);
        credential.setStatus(DeviceCredential.STATUS_ACTIVE);
        credential.setIssuedBy(CurrentUserService.currentUserId().orElse(null));
        if (rotation) {
            credential.setRotatedAt(LocalDateTime.now());
        } else {
            credential.setIssuedAt(LocalDateTime.now());
        }
        credential.setRevokedAt(null);

        String edgeToken = jwtService.issueEdgeToken(deviceId, device.getDeviceCode(), credential.getTokenVersion());
        credential.setTokenCipher(cipher.encrypt(edgeToken));
        repository.save(credential);

        auditService.userAction(AuditAction.CREDENTIAL_ISSUE, "device", device.getDeviceCode(),
                (rotation ? "轮换" : "签发") + "接入凭据，MQTT 账号 " + credential.getMqttUsername());
        return toView(device, credential, password, edgeToken);
    }

    /** 查看当前凭据（解密展示，便于重复部署边缘端）。 */
    public Optional<CredentialView> view(Long deviceId) {
        Device device = deviceLookupService.requireDevice(deviceId);
        return repository.findByDeviceId(deviceId)
                .map(credential -> toView(device, credential,
                        cipher.decrypt(credential.getSecretCipher()),
                        cipher.decrypt(credential.getTokenCipher())));
    }

    /** 吊销：清空令牌版本语义，边缘端必须重新签发才能上报。 */
    public CredentialView revoke(Long deviceId) {
        Device device = deviceLookupService.requireDevice(deviceId);
        DeviceCredential credential = repository.findByDeviceId(deviceId)
                .orElseThrow(() -> new IllegalArgumentException("device has no credential yet: " + device.getDeviceCode()));
        credential.setStatus(DeviceCredential.STATUS_REVOKED);
        credential.setTokenVersion(credential.getTokenVersion() + 1);
        credential.setRevokedAt(LocalDateTime.now());
        repository.save(credential);
        auditService.userAction(AuditAction.CREDENTIAL_REVOKE, "device", device.getDeviceCode(), "吊销接入凭据");
        return toView(device, credential, null, null);
    }

    @Override
    public boolean isTokenActive(Long deviceId, int tokenVersion) {
        return repository.findByDeviceId(deviceId)
                .filter(credential -> DeviceCredential.STATUS_ACTIVE.equals(credential.getStatus()))
                .filter(credential -> credential.getTokenVersion() == tokenVersion)
                .isPresent();
    }

    private CredentialView toView(Device device, DeviceCredential credential, String password, String edgeToken) {
        return new CredentialView(
                device.getId(),
                device.getDeviceCode(),
                device.getName(),
                credential.getStatus(),
                credential.getMqttUsername(),
                password,
                edgeToken,
                edgeToken == null ? null : OffsetDateTime.now(ZoneOffset.UTC)
                        .plusHours(jwtService.edgeTtlHours())
                        .format(DateTimeFormatter.ISO_INSTANT),
                brokerHost,
                brokerPort,
                List.of("robot/" + device.getDeviceCode() + "/cmd"),
                List.of(
                        "robot/" + device.getDeviceCode() + "/telemetry",
                        "robot/" + device.getDeviceCode() + "/heartbeat",
                        "robot/" + device.getDeviceCode() + "/event",
                        "robot/" + device.getDeviceCode() + "/cmd_ack"),
                credential.getIssuedAt(),
                credential.getRotatedAt());
    }

    private String mqttUsername(Device device, DeviceCredential credential) {
        String base = SAFE_USERNAME.matcher(device.getDeviceCode()).replaceAll("-");
        if (base.length() > 48) {
            base = base.substring(0, 48);
        }
        String candidate = base;
        int suffix = 1;
        while (usernameTakenByOther(candidate, credential)) {
            suffix++;
            candidate = base + "-" + suffix;
        }
        return candidate;
    }

    private boolean usernameTakenByOther(String candidate, DeviceCredential credential) {
        return repository.findByMqttUsername(candidate)
                .filter(existing -> credential.getId() == null || !existing.getId().equals(credential.getId()))
                .isPresent();
    }

    private static String randomSecret() {
        byte[] bytes = new byte[SECRET_BYTES];
        new SecureRandom().nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}