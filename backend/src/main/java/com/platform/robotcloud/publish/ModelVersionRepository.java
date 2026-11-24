package com.platform.robotcloud.publish;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface ModelVersionRepository extends JpaRepository<ModelVersion, Long> {

    @Query("select coalesce(max(m.version), 0) from ModelVersion m where m.deviceId = :deviceId and m.modelName = :modelName")
    int findMaxVersion(@Param("deviceId") Long deviceId, @Param("modelName") String modelName);

    Optional<ModelVersion> findByDeviceIdAndModelNameAndVersion(Long deviceId, String modelName, Integer version);

    List<ModelVersion> findByDeviceIdOrderByCreatedAtDesc(Long deviceId, Pageable pageable);

    List<ModelVersion> findByDeviceIdAndModelNameOrderByVersionDesc(Long deviceId, String modelName, Pageable pageable);

    List<ModelVersion> findByDeviceIdAndStatus(Long deviceId, String status);
}