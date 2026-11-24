package com.platform.robotcloud.device;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface DeviceRepository extends JpaRepository<Device, Long> {

    Optional<Device> findByDeviceCode(String deviceCode);

    List<Device> findByStatusOrderByIdAsc(String status);

    List<Device> findByStatus(String status, Pageable pageable);
}