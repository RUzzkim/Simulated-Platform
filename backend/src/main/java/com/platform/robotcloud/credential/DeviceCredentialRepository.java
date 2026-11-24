package com.platform.robotcloud.credential;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface DeviceCredentialRepository extends JpaRepository<DeviceCredential, Long> {

    Optional<DeviceCredential> findByDeviceId(Long deviceId);

    Optional<DeviceCredential> findByMqttUsername(String mqttUsername);

    boolean existsByMqttUsername(String mqttUsername);
}