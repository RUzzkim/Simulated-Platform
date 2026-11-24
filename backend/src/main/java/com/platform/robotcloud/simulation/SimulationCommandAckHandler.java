package com.platform.robotcloud.simulation;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.command.CommandLog;
import com.platform.robotcloud.command.CommandService;
import com.platform.robotcloud.mqtt.EdgeMessageHandler;
import com.platform.robotcloud.publish.PublishService;
import org.springframework.stereotype.Component;

/**
 * {@code simulation/{simulationId}/command_ack}：边端的指令回执。
 * <p>边端 {@code RobotCommand} 里的 {@code commandId} 与云端 {@code command_log.message_id}
 * 是同一个 UUID，所以这里可以直接复用 robot 契约的 {@link CommandService#recordAck}。
 * <p>没有这条回执，边端指令在界面上会永远停在 {@code PENDING}。
 */
@Component
public class SimulationCommandAckHandler implements EdgeMessageHandler {

    private final CommandService commandService;
    private final PublishService publishService;

    public SimulationCommandAckHandler(CommandService commandService, PublishService publishService) {
        this.commandService = commandService;
        this.publishService = publishService;
    }

    @Override
    public String topicSuffix() {
        return "command_ack";
    }

    @Override
    public boolean matches(String topic) {
        return SimulationTopics.simulationIdFromCommandAck(topic) != null;
    }

    @Override
    public void handle(String topic, JsonNode payload) {
        CommandLog command = commandService.recordAck(payload);
        publishService.applyAck(command);
    }
}