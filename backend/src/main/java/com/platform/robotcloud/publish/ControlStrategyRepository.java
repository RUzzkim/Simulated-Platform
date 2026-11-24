package com.platform.robotcloud.publish;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface ControlStrategyRepository extends JpaRepository<ControlStrategy, Long> {

    @Query("select coalesce(max(s.version), 0) from ControlStrategy s where s.name = :name")
    int findMaxVersion(@Param("name") String name);

    Optional<ControlStrategy> findByNameAndVersion(String name, Integer version);

    List<ControlStrategy> findAllByOrderByCreatedAtDesc(Pageable pageable);

    List<ControlStrategy> findByNameOrderByVersionDesc(String name, Pageable pageable);

    List<ControlStrategy> findByStatus(String status);
}