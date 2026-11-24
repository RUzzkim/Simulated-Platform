package com.platform.robotcloud.publish;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface ControlParameterRepository extends JpaRepository<ControlParameter, Long> {

    @Query("select coalesce(max(p.version), 0) from ControlParameter p where p.deviceId = :deviceId")
    int findMaxVersion(@Param("deviceId") Long deviceId);

    Optional<ControlParameter> findByDeviceIdAndVersion(Long deviceId, Integer version);

    List<ControlParameter> findByDeviceIdOrderByVersionDesc(Long deviceId, Pageable pageable);

    List<ControlParameter> findByDeviceIdAndStatus(Long deviceId, String status);
}