package com.platform.robotcloud.experiment;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;

import java.util.Optional;

public interface ExperimentRunRepository extends JpaRepository<ExperimentRun, Long>,
        JpaSpecificationExecutor<ExperimentRun> {

    Optional<ExperimentRun> findByRunId(String runId);
}
