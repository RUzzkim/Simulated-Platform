package com.platform.robotcloud.edge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import com.platform.robotcloud.command.CommandLog;
import com.platform.robotcloud.command.CommandLogRepository;
import com.platform.robotcloud.command.CommandService;
import com.platform.robotcloud.publish.PublishService;
import com.platform.robotcloud.event.FaultEvent;
import com.platform.robotcloud.event.FaultEventService;
import com.platform.robotcloud.heartbeat.HeartbeatService;
import com.platform.robotcloud.security.CurrentUserService;
import com.platform.robotcloud.security.EdgePrincipal;
import com.platform.robotcloud.support.ForbiddenException;
import com.platform.robotcloud.support.Payloads;
import com.platform.robotcloud.telemetry.TelemetryService;
import jakarta.validation.constraints.Min;
import org.springframework.data.domain.PageRequest;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 边缘端/仿真端的 HTTP 上报通道（对接边和端）：
 * 用设备凭据里的 edge token 鉴权（Authorization: Bearer），设备身份从令牌取，
 * 报文里的 deviceId 若与令牌不一致直接拒绝，避免越权写别的设备。
 * 适合只有 HTTP、不方便接 MQTT 的仿真端（Gazebo 桥接脚本等）；两条通道落库逻辑完全一致。
 */
@RestController
@RequestMapping("/api/edge")
public class EdgeReportController {

    public record Accepted(boolean accepted, String deviceCode, Long deviceId, LocalDateTime reportedAt) {
    }

    public record EdgeInfo(Long deviceId, String deviceCode, LocalDateTime serverTime,
                           List<String> subscribeTopics, List<String> publishTopics) {
    }

    private final TelemetryService telemetryService;
    private final HeartbeatService heartbeatService;
    private final FaultEventService faultEventService;
    private final CommandLogRepository commandLogRepository;
    private final CommandService commandService;
    private final PublishService publishService;
    private final AuditService auditService;
    private final ObjectMapper mapper = new ObjectMapper();

    public EdgeReportController(TelemetryService telemetryService,
                                HeartbeatService heartbeatService,
                                FaultEventService faultEventService,
                                CommandLogRepository commandLogRepository,
                                CommandService commandService,
                                PublishService publishService,
                                AuditService auditService) {
        this.telemetryService = telemetryService;
        this.heartbeatService = heartbeatService;
        this.faultEventService = faultEventService;
        this.commandLogRepository = commandLogRepository;
        this.commandService = commandService;
        this.publishService = publishService;
        this.auditService = auditService;
    }

    @PostMapping("/telemetry")
    public Accepted telemetry(@RequestBody(required = false) JsonNode body) {
        EdgePrincipal edge = requireEdge();
        JsonNode payload = withDeviceId(body, edge);
        var saved = telemetryService.saveTelemetry(payload);
        return new Accepted(true, edge.deviceCode(), edge.deviceId(),
                saved == null ? LocalDateTime.now() : saved.getReportedAt());
    }

    @PostMapping("/heartbeat")
    public Accepted heartbeat(@RequestBody(required = false) JsonNode body) {
        EdgePrincipal edge = requireEdge();
        JsonNode payload = withDeviceId(body, edge);
        heartbeatService.saveHeartbeat(payload);
        return new Accepted(true, edge.deviceCode(), edge.deviceId(), LocalDateTime.now());
    }

    @PostMapping("/event")
    public Accepted event(@RequestBody JsonNode body) {
        EdgePrincipal edge = requireEdge();
        JsonNode payload = withDeviceId(body, edge);
        FaultEvent event = faultEventService.saveEvent(payload);
        auditService.deviceAction(AuditAction.EDGE_EVENT, edge.deviceCode(), "device", edge.deviceCode(),
                "HTTP 上报故障事件 " + event.getEventType() + "/" + event.getLevel(), "SUCCESS");
        return new Accepted(true, edge.deviceCode(), edge.deviceId(), event.getOccurredAt());
    }

    /** HTTP 方式的边缘端可以主动拉取下发给自己的指令（MQTT 通道是订阅推送）。 */
    @GetMapping("/commands")
    public List<CommandLog> commands(@RequestParam(defaultValue = "20") @Min(1) int limit) {
        EdgePrincipal edge = requireEdge();
        return commandLogRepository.findByDeviceIdOrderByIssuedAtDesc(edge.deviceId(),
                PageRequest.of(0, Math.min(Math.max(limit, 1), 100)));
    }

    /** HTTP 方式的边缘端上报指令执行结果（MQTT 通道走 robot/&lt;code&gt;/cmd_ack）。 */
    @PostMapping("/cmd-ack")
    public Accepted cmdAck(@RequestBody JsonNode body) {
        EdgePrincipal edge = requireEdge();
        JsonNode payload = withDeviceId(body, edge);
        String messageId = Payloads.text(payload, "messageId", Payloads.text(payload, "cmdId", null));
        if (messageId == null) {
            throw new IllegalArgumentException("cmd-ack 缺少 messageId");
        }
        commandLogRepository.findByMessageId(messageId).ifPresent(command -> {
            if (!edge.deviceId().equals(command.getDeviceId())) {
                throw new ForbiddenException("指令 " + messageId + " 不属于设备 " + edge.deviceCode());
            }
        });
        // 与 MQTT 通道一致：回执成功后同步参数/策略/模型的版本状态
        publishService.applyAck(commandService.recordAck(payload));
        return new Accepted(true, edge.deviceCode(), edge.deviceId(), LocalDateTime.now());
    }

    @GetMapping("/me")
    public EdgeInfo me() {
        EdgePrincipal edge = requireEdge();
        return new EdgeInfo(edge.deviceId(), edge.deviceCode(), LocalDateTime.now(),
                List.of("robot/" + edge.deviceCode() + "/cmd"),
                List.of(
                        "robot/" + edge.deviceCode() + "/telemetry",
                        "robot/" + edge.deviceCode() + "/heartbeat",
                        "robot/" + edge.deviceCode() + "/event",
                        "robot/" + edge.deviceCode() + "/cmd_ack"));
    }

    private EdgePrincipal requireEdge() {
        return CurrentUserService.edge()
                .orElseThrow(() -> new ForbiddenException("需要设备接入令牌（edge token）"));
    }

    private JsonNode withDeviceId(JsonNode body, EdgePrincipal edge) {
        String claimed = body == null ? null : Payloads.deviceCode(body);
        if (claimed != null && !claimed.equals(edge.deviceCode())) {
            auditService.deviceAction(AuditAction.EDGE_EVENT, edge.deviceCode(), "device", claimed,
                    "上报报文 deviceId 与令牌不一致", "FAILURE");
            throw new ForbiddenException("报文 deviceId(" + claimed + ") 与令牌设备(" + edge.deviceCode() + ")不一致");
        }
        ObjectNode node = body != null && body.isObject()
                ? ((ObjectNode) body).deepCopy()
                : mapper.createObjectNode();
        node.put("deviceId", edge.deviceCode());
        return node;
    }
}