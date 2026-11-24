package com.platform.robotcloud.audit;

import com.platform.robotcloud.security.CurrentUserService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

/**
 * 审计写入入口。审计失败绝不影响主流程，只记日志。
 */
@Service
public class AuditService {

    private static final Logger log = LoggerFactory.getLogger(AuditService.class);

    private static final int DETAIL_MAX = 500;
    private static final int ERROR_MAX = 250;

    private final AuditLogRepository repository;

    public AuditService(AuditLogRepository repository) {
        this.repository = repository;
    }

    /** 当前登录用户发起且成功的操作。 */
    public void userAction(String action, String targetType, String targetId, String detail) {
        CurrentUserService.current().ifPresentOrElse(
                user -> namedActor(action, "USER", user.id(), user.username(), targetType, targetId, detail, "SUCCESS", null),
                () -> namedActor(action, "SYSTEM", null, "system", targetType, targetId, detail, "SUCCESS", null));
    }

    /** 当前登录用户发起但失败的操作。 */
    public void userFailure(String action, String targetType, String targetId, String detail, String error) {
        CurrentUserService.current().ifPresentOrElse(
                user -> namedActor(action, "USER", user.id(), user.username(), targetType, targetId, detail, "FAILURE", error),
                () -> namedActor(action, "SYSTEM", null, "system", targetType, targetId, detail, "FAILURE", error));
    }

    /** 登录这类还没有身份的场景：显式给出尝试的用户名。 */
    public void attemptFailure(String action, String actorName, String targetType, String targetId, String detail) {
        namedActor(action, "ANONYMOUS", null, actorName, targetType, targetId, detail, "FAILURE", "认证失败");
    }

    /** 边缘端/仿真端（设备身份）的动作。 */
    public void deviceAction(String action, String deviceCode, String targetType, String targetId,
                             String detail, String result) {
        String actorName = deviceCode == null ? "unknown-device" : deviceCode;
        namedActor(action, "DEVICE", null, actorName, targetType, targetId, detail, result, null);
    }

    public void namedActor(String action, String actorType, Long actorId, String actorName,
                           String targetType, String targetId, String detail, String result, String errorMessage) {
        try {
            AuditLog entry = new AuditLog();
            entry.setAction(action);
            entry.setActorType(actorType);
            entry.setActorId(actorId);
            entry.setActorName(actorName);
            entry.setTargetType(targetType);
            entry.setTargetId(targetId);
            entry.setDetail(truncate(detail, DETAIL_MAX));
            entry.setResult(result);
            entry.setErrorMessage(truncate(errorMessage, ERROR_MAX));
            entry.setClientIp(CurrentUserService.clientIp());
            entry.setOccurredAt(LocalDateTime.now());
            repository.save(entry);
        } catch (Exception ex) {
            log.warn("failed to write audit log for action {}: {}", action, ex.getMessage());
        }
    }

    private static String truncate(String value, int max) {
        if (value == null || value.length() <= max) {
            return value;
        }
        return value.substring(0, max - 3) + "...";
    }
}