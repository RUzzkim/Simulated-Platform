package com.platform.robotcloud.security;

import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 首次启动（app_user 为空）时初始化管理员，避免部署后无人能登录。
 * 本地联调可打开 ADMIN_SEED_DEMO_USERS 再建一个操作员和一个只读账号，方便演示角色差异。
 */
@Component
public class AdminBootstrap implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(AdminBootstrap.class);

    private static final String DEFAULT_ADMIN_PASSWORD = "admin123456";
    private static final String DEFAULT_OPERATOR_PASSWORD = "operator123456";
    private static final String DEFAULT_VIEWER_PASSWORD = "viewer123456";

    private final AppUserRepository repository;
    private final PasswordEncoder passwordEncoder;
    private final AuditService auditService;
    private final String adminUsername;
    private final String adminPassword;
    private final boolean seedDemoUsers;

    public AdminBootstrap(AppUserRepository repository,
                          PasswordEncoder passwordEncoder,
                          AuditService auditService,
                          @Value("${app.admin.username:admin}") String adminUsername,
                          @Value("${app.admin.password:}") String adminPassword,
                          @Value("${app.admin.seed-demo-users:false}") boolean seedDemoUsers) {
        this.repository = repository;
        this.passwordEncoder = passwordEncoder;
        this.auditService = auditService;
        this.adminUsername = adminUsername;
        this.adminPassword = adminPassword;
        this.seedDemoUsers = seedDemoUsers;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (repository.count() > 0) {
            return;
        }
        boolean generated = adminPassword == null || adminPassword.isBlank();
        create(adminUsername, generated ? DEFAULT_ADMIN_PASSWORD : adminPassword, "平台管理员", Role.ADMIN);
        if (generated) {
            log.warn("未配置 ADMIN_PASSWORD，已使用默认管理员口令：{} / {}（请登录后立即修改）",
                    adminUsername, DEFAULT_ADMIN_PASSWORD);
        }
        if (seedDemoUsers) {
            create("operator", DEFAULT_OPERATOR_PASSWORD, "运维操作员", Role.OPERATOR);
            create("viewer", DEFAULT_VIEWER_PASSWORD, "只读观察员", Role.VIEWER);
            log.warn("已创建演示账号 operator/{} 与 viewer/{}（生产请设置 ADMIN_SEED_DEMO_USERS=false）",
                    DEFAULT_OPERATOR_PASSWORD, DEFAULT_VIEWER_PASSWORD);
        }
        auditService.namedActor(AuditAction.ADMIN_BOOTSTRAP, "SYSTEM", null, "system", "user", adminUsername,
                "初始化管理员账号", "SUCCESS", null);
    }

    private void create(String username, String rawPassword, String displayName, Role role) {
        AppUser user = new AppUser();
        user.setUsername(username);
        user.setDisplayName(displayName);
        user.setPasswordHash(passwordEncoder.encode(rawPassword));
        user.setRole(role.name());
        user.setEnabled(true);
        user.setStatus(UserStatus.APPROVED.name());
        user.setCreatedAt(LocalDateTime.now());
        user.setUpdatedAt(LocalDateTime.now());
        repository.save(user);
        log.info("created {} account: {}", role, username);
    }
}