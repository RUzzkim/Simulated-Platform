package com.platform.robotcloud.command;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface CommandLogRepository extends JpaRepository<CommandLog, Long> {

    Optional<CommandLog> findByMessageId(String messageId);

    List<CommandLog> findByDeviceIdOrderByIssuedAtDesc(Long deviceId, Pageable pageable);
}