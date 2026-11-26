package com.platform.robotcloud.experiment;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ExperimentEventRepository extends JpaRepository<ExperimentEvent, Long> {

    List<ExperimentEvent> findByRunIdOrderByEventTimeAscIdAsc(String runId);

    boolean existsByEventKey(String eventKey);
}
