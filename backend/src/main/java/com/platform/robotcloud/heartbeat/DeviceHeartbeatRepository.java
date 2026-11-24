package com.platform.robotcloud.heartbeat;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface DeviceHeartbeatRepository extends JpaRepository<DeviceHeartbeat, Long> {

    Optional<DeviceHeartbeat> findFirstByDeviceIdOrderByReportedAtDesc(Long deviceId);
}