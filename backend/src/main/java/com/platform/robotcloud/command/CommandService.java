package com.platform.robotcloud.command;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.platform.robotcloud.device.Device;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.mqtt.MqttPublisher;
import com.platform.robotcloud.security.CurrentUser;
import com.platform.robotcloud.security.CurrentUserService;
import com.platform.robotcloud.support.Payloads;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Service
public class CommandService {

    private static final Logger log = LoggerFactory.getLogger(CommandService.class);

    private static final int DETAIL_MAX_LENGTH = 255;

    private final CommandLogRepository repository;
    private final DeviceLookupService deviceLookupService;
    private final MqttPublisher publisher;
    private final AuditService auditService;
    private final ObjectMapper mapper = new ObjectMapper();

    public CommandService(CommandLogRepository repository,
                          DeviceLookupService deviceLookupService,
                          MqttPublisher publisher,
                          AuditService auditService) {
        this.repository = repository;
        this.deviceLookupService = deviceLookupService;
        this.publisher = publisher;
        this.auditService = auditService;
    }

    public CommandLog dispatch(Long deviceId, CommandRequest request) {
        Device device = deviceLookupService.requireDevice(deviceId);
        String messageId = UUID.randomUUID().toString();

        // 绑定过 simulationId 的设备 = 边端，走 simulation 契约；其余走本项目原生的 robot 契约。
        SimulationCommand.Prepared edge = isSimulationDevice(device)
                ? SimulationCommand.prepare(device, request, messageId)
                : null;
        JsonNode payload = edge != null
                ? edge.payload()
                : (request.payload() == null ? mapper.createObjectNode() : request.payload());
        String topic = edge != null
                ? "simulation/" + device.getSimulationId() + "/command"
                : "robot/" + device.getDeviceCode() + "/cmd";

        CommandLog commandLog = new CommandLog();
        commandLog.setDeviceId(deviceId);
        commandLog.setMessageId(messageId);
        commandLog.setCmdType(request.cmdType());
        commandLog.setVersion(request.version());
        commandLog.setPayload(payload.toString());
        if (edge != null) {
            commandLog.setSimulationId(device.getSimulationId());
            commandLog.setTargetRobotId(device.getDeviceCode());
        }
        CurrentUser operator = CurrentUserService.current().orElse(null);
        if (operator != null) {
            commandLog.setIssuedBy(operator.id());
            commandLog.setIssuedByName(operator.username());
        }
        commandLog.setIssuedAt(LocalDateTime.now());
        commandLog.setResult("PENDING");
        repository.save(commandLog);

        // 边端报文由 SimulationCommand 构造（字段严格对齐边端 RobotCommand）
        String body = edge != null ? edge.body().toString() : envelope(messageId, device.getDeviceCode(), request, payload);
        try {
            publisher.publish(topic, body);
            log.info("dispatched command {} ({}) to {}", messageId, request.cmdType(), topic);
            auditService.userAction(AuditAction.COMMAND_DISPATCH, "device", device.getDeviceCode(),
                    "下发 " + request.cmdType() + " 指令 messageId=" + messageId);
        } catch (Exception ex) {
            log.error("failed to dispatch command {} to {}", messageId, topic, ex);
            commandLog.setResult("FAILED");
            commandLog.setResultDetail(truncate(ex.getMessage()));
            repository.save(commandLog);
            auditService.userFailure(AuditAction.COMMAND_DISPATCH, "device", device.getDeviceCode(),
                    "下发 " + request.cmdType() + " 指令 messageId=" + messageId, truncate(ex.getMessage()));
        }
        return commandLog;
    }

    /** 记录回执；返回更新后的记录（messageId 缺失或未知时返回 null），供版本状态机同步。 */
    public CommandLog recordAck(JsonNode json) {
        // 边端（simulation 契约）回的是 commandId；commandId == command_log.message_id
        String messageId = Payloads.text(json, "messageId",
                Payloads.text(json, "cmdId", Payloads.text(json, "commandId", null)));
        if (messageId == null) {
            log.warn("cmd_ack without messageId was ignored: {}", json);
            return null;
        }
        Optional<CommandLog> found = repository.findByMessageId(messageId);
        if (found.isEmpty()) {
            log.warn("cmd_ack for unknown command {} was ignored", messageId);
            return null;
        }
        CommandLog commandLog = found.get();
        commandLog.setResult(Payloads.text(json, "result", "SUCCESS"));
        commandLog.setResultDetail(truncate(Payloads.text(json, "detail", null)));
        commandLog.setAcknowledgedAt(Payloads.reportedAt(json));
        repository.save(commandLog);
        log.info("command {} acknowledged with {}", messageId, commandLog.getResult());
        auditService.deviceAction(AuditAction.COMMAND_ACK, ackActor(json), "command", messageId,
                "指令回执 " + commandLog.getResult() + (commandLog.getResultDetail() == null ? "" : "：" + commandLog.getResultDetail()),
                commandLog.getResult());
        return commandLog;
    }

    public List<CommandLog> history(Long deviceId, int page, int size) {
        deviceLookupService.requireDevice(deviceId);
        return repository.findByDeviceIdOrderByIssuedAtDesc(deviceId, PageRequest.of(page, size));
    }

    /** 回执的“设备”标识：robot 契约用 deviceId，simulation 契约用 robotId 兜底。 */
    private static String ackActor(JsonNode json) {
        return Payloads.text(json, "deviceId", Payloads.text(json, "robotId", null));
    }

    private static boolean isSimulationDevice(Device device) {
        return device.getSimulationId() != null && !device.getSimulationId().isBlank();
    }

    private String envelope(String messageId, String deviceCode, CommandRequest request, JsonNode payload) {
        ObjectNode envelope = mapper.createObjectNode();
        envelope.put("messageId", messageId);
        envelope.put("deviceId", deviceCode);
        envelope.put("timestamp", OffsetDateTime.now(ZoneOffset.UTC).format(DateTimeFormatter.ISO_INSTANT));
        envelope.put("cmdType", request.cmdType());
        if (request.version() == null) {
            envelope.putNull("version");
        } else {
            envelope.put("version", request.version());
        }
        envelope.set("payload", payload);
        return envelope.toString();
    }

    private static String truncate(String value) {
        if (value == null || value.length() <= DETAIL_MAX_LENGTH) {
            return value;
        }
        return value.substring(0, DETAIL_MAX_LENGTH - 3) + "...";
    }
}