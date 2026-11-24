package com.platform.robotcloud.telemetry;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface TelemetryHourlyRepository extends JpaRepository<TelemetryHourly, Long> {

    Optional<TelemetryHourly> findByDeviceIdAndBucketStart(Long deviceId, LocalDateTime bucketStart);

    List<TelemetryHourly> findByDeviceIdAndBucketStartBetweenOrderByBucketStartAsc(
            Long deviceId, LocalDateTime from, LocalDateTime to);

    Optional<TelemetryHourly> findTopByOrderByArchivedAtDesc();
}