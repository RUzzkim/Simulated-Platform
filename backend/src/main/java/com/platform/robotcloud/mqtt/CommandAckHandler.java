package com.platform.robotcloud.mqtt;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.command.CommandLog;
import com.platform.robotcloud.command.CommandService;
import com.platform.robotcloud.publish.PublishService;
import org.springframework.stereotype.Component;

@Component
public class CommandAckHandler implements EdgeMessageHandler {

    private final CommandService service;
    private final PublishService publishService;

    public CommandAckHandler(CommandService service, PublishService publishService) {
        this.service = service;
        this.publishService = publishService;
    }

    @Override
    public String topicSuffix() {
        return "cmd_ack";
    }

    @Override
    public void handle(JsonNode payload) {
        CommandLog command = service.recordAck(payload);
        // 参数/策略/模型下发成功后把版本置为 ACTIVE（失败回执只记 command_log）
        publishService.applyAck(command);
    }
}