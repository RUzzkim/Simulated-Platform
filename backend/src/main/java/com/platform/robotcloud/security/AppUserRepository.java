package com.platform.robotcloud.security;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface AppUserRepository extends JpaRepository<AppUser, Long> {

    Optional<AppUser> findByUsername(String username);

    boolean existsByUsername(String username);

    List<AppUser> findAllByOrderByIdAsc();

    /** 仅统计「已批准且启用」的某角色账号，作为最后一个管理员的判据。 */
    long countByRoleAndEnabledTrueAndStatus(String role, String status);
}