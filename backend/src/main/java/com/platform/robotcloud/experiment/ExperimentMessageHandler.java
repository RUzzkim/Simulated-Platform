package com.platform.robotcloud.experiment;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.mqtt.EdgeMessageHandler;
import com.platform.robotcloud.simulation.SimulationTopics;
import org.springframework.stereotype.Component;

/**
 * {@code simulation/{simulationId}/experiment_run} 与
 * {@code simulation/{simulationId}/experiment_event}：V2 实验 Run 与事件入库。
 */
@Component
public class ExperimentMessageHandler implements EdgeMessageHandler {

    private final ExperimentService service;

    public ExperimentMessageHandler(ExperimentService service) {
        this.service = service;
    }

    @Override
    public String topicSuffix() {
        return "experiment_run";
    }

    @Override
    public boolean matches(String topic) {
        return SimulationTopics.simulationIdFromExperimentRun(topic) != null
                || SimulationTopics.simulationIdFromExperimentEvent(topic) != null;
    }

    @Override
    public void handle(String topic, JsonNode payload) {
        if (SimulationTopics.simulationIdFromExperimentRun(topic) != null) {
            service.ingestRun(payload);
        } else {
            service.ingestEvent(payload);
        }
    }
}
