package com.platform.robotcloud.security;

import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 账号管理（仅 ADMIN）：创建用户、调整角色/启用状态、重置密码。
 * 不能停用/降级自己，也不能让系统失去最后一个可用的 ADMIN。
 */
@RestController
@RequestMapping("/api/users")
public class UserController {

    public record CreateRequest(@NotBlank String username,
                                @NotBlank @Size(min = 8, message = "密码至少 8 位") String password,
                                String displayName,
                                @NotBlank String role) {
    }

    public record UpdateRequest(String displayName, String role, Boolean enabled) {
    }

    public record ResetPasswordRequest(@NotBlank @Size(min = 8, message = "密码至少 8 位") String password) {
    }

    /** 审批时可选地修正意向角色；不传则沿用申请人填的角色。 */
    public record ApproveRequest(String role) {
    }

    private final AppUserRepository repository;
    private final PasswordEncoder passwordEncoder;
    private final AuditService auditService;

    public UserController(AppUserRepository repository, PasswordEncoder passwordEncoder, AuditService auditService) {
        this.repository = repository;
        this.passwordEncoder = passwordEncoder;
        this.auditService = auditService;
    }

    @GetMapping
    public List<AuthController.UserView> list() {
        return repository.findAllByOrderByIdAsc().stream().map(AuthController.UserView::of).toList();
    }

    @PostMapping
    public AuthController.UserView create(@Valid @RequestBody CreateRequest request) {
        String username = request.username().trim();
        if (repository.existsByUsername(username)) {
            auditService.userFailure(AuditAction.USER_CREATE, "user", username, "创建用户 " + username, "用户名已存在");
            throw new IllegalArgumentException("用户名已存在: " + username);
        }
        Role role = Role.of(request.role());
        AppUser user = new AppUser();
        user.setUsername(username);
        user.setDisplayName(blankToNull(request.displayName()));
        user.setPasswordHash(passwordEncoder.encode(request.password()));
        user.setRole(role.name());
        user.setEnabled(true);
        // ADMIN 直接建号即视为已审批，可立即登录
        user.setStatus(UserStatus.APPROVED.name());
        user.setCreatedAt(LocalDateTime.now());
        user.setUpdatedAt(LocalDateTime.now());
        AppUser saved = repository.save(user);
        auditService.userAction(AuditAction.USER_CREATE, "user", String.valueOf(saved.getId()),
                "创建用户 " + username + "（" + role + "）");
        return AuthController.UserView.of(saved);
    }

    /** 审批通过一个待审账号：置 APPROVED 并启用，可选时顺带修正角色。 */
    @PostMapping("/{id}/approve")
    public AuthController.UserView approve(@PathVariable Long id, @RequestBody(required = false) ApproveRequest request) {
        AppUser user = requireUser(id);
        if (!UserStatus.PENDING.name().equals(user.getStatus())) {
            throw new IllegalArgumentException("只能审批待审批（PENDING）状态的账号");
        }
        if (request != null && request.role() != null && !request.role().isBlank()) {
            user.setRole(Role.of(request.role()).name());
        }
        user.setStatus(UserStatus.APPROVED.name());
        user.setEnabled(true);
        user.setUpdatedAt(LocalDateTime.now());
        AppUser saved = repository.save(user);
        auditService.userAction(AuditAction.USER_APPROVE, "user", String.valueOf(id),
                "审批通过用户 " + saved.getUsername() + "（" + saved.getRole() + "）");
        return AuthController.UserView.of(saved);
    }

    /** 驳回一个待审账号：置 REJECTED 并保持停用，账号保留以便审计。 */
    @PostMapping("/{id}/reject")
    public AuthController.UserView reject(@PathVariable Long id) {
        AppUser user = requireUser(id);
        if (!UserStatus.PENDING.name().equals(user.getStatus())) {
            throw new IllegalArgumentException("只能驳回待审批（PENDING）状态的账号");
        }
        user.setStatus(UserStatus.REJECTED.name());
        user.setEnabled(false);
        user.setUpdatedAt(LocalDateTime.now());
        AppUser saved = repository.save(user);
        auditService.userAction(AuditAction.USER_REJECT, "user", String.valueOf(id),
                "驳回用户 " + saved.getUsername() + " 的注册申请");
        return AuthController.UserView.of(saved);
    }

    @PutMapping("/{id}")
    public AuthController.UserView update(@PathVariable Long id, @RequestBody UpdateRequest request) {
        AppUser user = requireUser(id);
        CurrentUser current = CurrentUserService.current().orElse(null);
        boolean self = current != null && current.id().equals(id);

        if (request.displayName() != null) {
            user.setDisplayName(blankToNull(request.displayName()));
        }
        if (request.role() != null) {
            Role role = Role.of(request.role());
            ensureNotLastAdmin(user, role.name(), "不能把最后一个管理员降级");
            if (self && role != Role.ADMIN) {
                throw new IllegalArgumentException("不能修改自己的角色，请让其他管理员操作");
            }
            user.setRole(role.name());
        }
        if (request.enabled() != null) {
            if (self && !request.enabled()) {
                throw new IllegalArgumentException("不能停用当前登录的账号");
            }
            if (!request.enabled()) {
                ensureNotLastAdmin(user, null, "不能停用最后一个管理员");
            }
            user.setEnabled(request.enabled());
        }
        user.setUpdatedAt(LocalDateTime.now());
        AppUser saved = repository.save(user);
        auditService.userAction(AuditAction.USER_UPDATE, "user", String.valueOf(id),
                "更新用户 " + saved.getUsername() + " 角色=" + saved.getRole() + " 启用=" + saved.isEnabled());
        return AuthController.UserView.of(saved);
    }

    @PostMapping("/{id}/password")
    public AuthController.UserView resetPassword(@PathVariable Long id, @Valid @RequestBody ResetPasswordRequest request) {
        AppUser user = requireUser(id);
        user.setPasswordHash(passwordEncoder.encode(request.password()));
        user.setUpdatedAt(LocalDateTime.now());
        AppUser saved = repository.save(user);
        auditService.userAction(AuditAction.PASSWORD_CHANGE, "user", String.valueOf(id),
                "重置用户 " + saved.getUsername() + " 的密码");
        return AuthController.UserView.of(saved);
    }

    private AppUser requireUser(Long id) {
        return repository.findById(id).orElseThrow(() -> new IllegalArgumentException("user not found: " + id));
    }

    /** 只有“确实会让管理员变少”的操作才拦截：目标唯一启用的 ADMIN 降级或停用时拒绝。 */
    private void ensureNotLastAdmin(AppUser target, String newRole, String message) {
        if (!Role.ADMIN.name().equals(target.getRole()) || !target.isEnabled()) {
            return;
        }
        boolean removingAdmin = newRole == null || !Role.ADMIN.name().equals(newRole);
        if (!removingAdmin) {
            return;
        }
        if (repository.countByRoleAndEnabledTrueAndStatus(Role.ADMIN.name(), UserStatus.APPROVED.name()) <= 1) {
            throw new IllegalArgumentException(message);
        }
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }
}