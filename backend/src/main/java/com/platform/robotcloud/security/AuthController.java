package com.platform.robotcloud.security;

import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import com.platform.robotcloud.support.UnauthorizedException;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;

/**
 * 登录 / 当前用户 / 自助改密。令牌无状态，登出由前端丢弃令牌即可。
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    public record LoginRequest(@NotBlank String username, @NotBlank String password) {
    }

    public record UserView(Long id, String username, String displayName, String role, boolean enabled,
                           String status, LocalDateTime lastLoginAt) {
        public static UserView of(AppUser user) {
            return new UserView(user.getId(), user.getUsername(), user.getDisplayName(), user.getRole(),
                    user.isEnabled(), user.getStatus(), user.getLastLoginAt());
        }
    }

    public record RegisterRequest(@NotBlank @Size(max = 64) String username,
                                  @NotBlank @Size(min = 8, message = "密码至少 8 位") String password,
                                  String displayName,
                                  @NotBlank String role) {
    }

    public record LoginResponse(String token, long expiresInMinutes, UserView user) {
    }

    public record ChangePasswordRequest(@NotBlank String currentPassword,
                                        @NotBlank @Size(min = 8, message = "新密码至少 8 位") String newPassword) {
    }

    private final AppUserRepository repository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final AuditService auditService;

    public AuthController(AppUserRepository repository,
                          PasswordEncoder passwordEncoder,
                          JwtService jwtService,
                          AuditService auditService) {
        this.repository = repository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.auditService = auditService;
    }

    @PostMapping("/login")
    public LoginResponse login(@Valid @RequestBody LoginRequest request) {
        String username = request.username().trim();
        AppUser user = repository.findByUsername(username).orElse(null);
        if (user == null || !passwordEncoder.matches(request.password(), user.getPasswordHash())) {
            auditService.attemptFailure(AuditAction.LOGIN, username, "user", username, "登录失败");
            throw new UnauthorizedException("用户名或密码错误");
        }
        // 密码正确但账号还没放行：区分「待审批 / 已驳回 / 被停用」，给运维和用户一个明确说法
        if (UserStatus.PENDING.name().equals(user.getStatus())) {
            auditService.attemptFailure(AuditAction.LOGIN, username, "user", username, "账号待管理员审批");
            throw new UnauthorizedException("账号正在等待管理员审批，请稍后再试");
        }
        if (UserStatus.REJECTED.name().equals(user.getStatus())) {
            auditService.attemptFailure(AuditAction.LOGIN, username, "user", username, "账号已被驳回");
            throw new UnauthorizedException("账号注册申请已被驳回，请联系管理员");
        }
        if (!user.isEnabled()) {
            auditService.attemptFailure(AuditAction.LOGIN, username, "user", username, "账号已停用");
            throw new UnauthorizedException("账号已被停用，请联系管理员");
        }
        user.setLastLoginAt(LocalDateTime.now());
        user.setUpdatedAt(LocalDateTime.now());
        repository.save(user);
        auditService.namedActor(AuditAction.LOGIN, "USER", user.getId(), user.getUsername(), "user",
                String.valueOf(user.getId()), "登录成功", "SUCCESS", null);
        return new LoginResponse(jwtService.issueUserToken(user), jwtService.userTtlMinutes(), UserView.of(user));
    }

    /**
     * 自助注册：任何人可提交，落库为 PENDING（未启用），等 ADMIN 审批。
     * 不返回令牌——审批通过前不能登录。角色是申请的意向角色，最终以审批为准。
     */
    @PostMapping("/register")
    public UserView register(@Valid @RequestBody RegisterRequest request) {
        String username = request.username().trim();
        Role role = Role.of(request.role());
        if (repository.existsByUsername(username)) {
            auditService.attemptFailure(AuditAction.USER_REGISTER, username, "user", username, "注册失败：用户名已存在");
            throw new IllegalArgumentException("用户名已存在: " + username);
        }
        AppUser user = new AppUser();
        user.setUsername(username);
        String displayName = request.displayName() == null || request.displayName().isBlank()
                ? null : request.displayName().trim();
        user.setDisplayName(displayName);
        user.setPasswordHash(passwordEncoder.encode(request.password()));
        user.setRole(role.name());
        user.setEnabled(false);
        user.setStatus(UserStatus.PENDING.name());
        user.setCreatedAt(LocalDateTime.now());
        user.setUpdatedAt(LocalDateTime.now());
        AppUser saved = repository.save(user);
        auditService.namedActor(AuditAction.USER_REGISTER, "ANONYMOUS", null, username, "user",
                String.valueOf(saved.getId()), "自助注册申请（意向角色 " + role + "）待审批", "SUCCESS", null);
        return UserView.of(saved);
    }

    @GetMapping("/me")
    public UserView me() {
        CurrentUser current = CurrentUserService.current()
                .orElseThrow(() -> new UnauthorizedException("unauthorized"));
        AppUser user = repository.findById(current.id())
                .orElseThrow(() -> new UnauthorizedException("user no longer exists"));
        return UserView.of(user);
    }

    @PostMapping("/password")
    public UserView changePassword(@Valid @RequestBody ChangePasswordRequest request) {
        CurrentUser current = CurrentUserService.current()
                .orElseThrow(() -> new UnauthorizedException("unauthorized"));
        AppUser user = repository.findById(current.id())
                .orElseThrow(() -> new UnauthorizedException("user no longer exists"));
        if (!passwordEncoder.matches(request.currentPassword(), user.getPasswordHash())) {
            auditService.userFailure(AuditAction.PASSWORD_CHANGE, "user", String.valueOf(user.getId()), "修改密码", "原密码错误");
            throw new IllegalArgumentException("原密码错误");
        }
        user.setPasswordHash(passwordEncoder.encode(request.newPassword()));
        user.setUpdatedAt(LocalDateTime.now());
        repository.save(user);
        auditService.userAction(AuditAction.PASSWORD_CHANGE, "user", String.valueOf(user.getId()), "修改本人密码");
        return UserView.of(user);
    }
}