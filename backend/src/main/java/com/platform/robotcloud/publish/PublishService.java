package com.platform.robotcloud.publish;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import com.platform.robotcloud.command.CommandLog;
import com.platform.robotcloud.command.CommandRequest;
import com.platform.robotcloud.command.CommandService;
import com.platform.robotcloud.device.Device;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.security.CurrentUser;
import com.platform.robotcloud.security.CurrentUserService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 参数 / 策略 / 模型版本化与下发。
 *
 * <p>版本行不可变：新增即产生新版本，下发只改状态；旧版本重新下发就等于回滚。
 * 下发复用 {@link CommandService}，因此 command_log 里能看到每一次下发的 messageId、
 * 载荷与回执，边缘端回执成功（cmd_ack result=SUCCESS）后版本才置为 ACTIVE。
 */
@Service
public class PublishService {

    private static final Logger log = LoggerFactory.getLogger(PublishService.class);

    public static final String CMD_PARAMETER = "PARAMETER";
    public static final String CMD_STRATEGY = "STRATEGY";
    public static final String CMD_MODEL = "MODEL";

    private static final int MAX_LIST = 200;
    private static final Pattern NAME_PATTERN = Pattern.compile("^[A-Za-z0-9_.-]{1,64}$");

    /** 静态 mapper：toView 是 static，不能复用实例字段。 */
    private static final ObjectMapper JSON = new ObjectMapper();

    private final ControlParameterRepository parameterRepository;
    private final ControlStrategyRepository strategyRepository;
    private final ModelVersionRepository modelRepository;
    private final CommandService commandService;
    private final DeviceLookupService deviceLookupService;
    private final AuditService auditService;
    private final ObjectMapper mapper = new ObjectMapper();

    public PublishService(ControlParameterRepository parameterRepository,
                          ControlStrategyRepository strategyRepository,
                          ModelVersionRepository modelRepository,
                          CommandService commandService,
                          DeviceLookupService deviceLookupService,
                          AuditService auditService) {
        this.parameterRepository = parameterRepository;
        this.strategyRepository = strategyRepository;
        this.modelRepository = modelRepository;
        this.commandService = commandService;
        this.deviceLookupService = deviceLookupService;
        this.auditService = auditService;
    }

    // ------------------------------------------------------------------ 参数

    public ParameterView createParameter(Long deviceId, JsonNode payload) {
        Device device = deviceLookupService.requireDevice(deviceId);
        JsonNode body = requireObject(payload, "payload");
        ControlParameter row = new ControlParameter();
        row.setDeviceId(deviceId);
        row.setVersion(parameterRepository.findMaxVersion(deviceId) + 1);
        row.setParamPayload(body.toString());
        row.setStatus(PublishStatus.DRAFT);
        stampCreator(row::setCreatedBy, row::setCreatedByName);
        row.setCreatedAt(LocalDateTime.now());
        ControlParameter saved = parameterRepository.save(row);
        auditService.userAction(AuditAction.PARAMETER_CREATE, "device", device.getDeviceCode(),
                "新增参数版本 v" + saved.getVersion());
        return toView(saved);
    }

    public List<ParameterView> parameters(Long deviceId, int limit) {
        deviceLookupService.requireDevice(deviceId);
        return parameterRepository.findByDeviceIdOrderByVersionDesc(deviceId, PageRequest.of(0, cap(limit)))
                .stream().map(PublishService::toView).toList();
    }

    public ParameterView parameter(Long deviceId, int version) {
        return toView(requireParameter(deviceId, version));
    }

    public PublishResult publishParameter(Long deviceId, int version) {
        ControlParameter row = requireParameter(deviceId, version);
        boolean rollback = version < parameterRepository.findMaxVersion(deviceId);
        JsonNode payload = parse(row.getParamPayload());
        PublishResult result = dispatch(deviceId, CMD_PARAMETER, version, payload, rollback,
                AuditAction.PARAMETER_PUBLISH, "参数 v" + version);
        // 只把 DRAFT 推进到 PUBLISHED：重复下发当前 ACTIVE 的版本时保持 ACTIVE，
        // 否则一条失败回执会把「设备正在跑的配置」从云端视角抹掉。
        if (!"FAILED".equals(result.commandResult()) && PublishStatus.DRAFT.equals(row.getStatus())) {
            row.setStatus(PublishStatus.PUBLISHED);
            parameterRepository.save(row);
        }
        return withStatus(result, row.getStatus());
    }

    // ------------------------------------------------------------------ 模型

    public ModelView createModel(Long deviceId, String modelName, String artifactUrl, JsonNode metadata) {
        Device device = deviceLookupService.requireDevice(deviceId);
        String name = requireName(modelName, "modelName");
        ModelVersion row = new ModelVersion();
        row.setDeviceId(deviceId);
        row.setModelName(name);
        row.setVersion(modelRepository.findMaxVersion(deviceId, name) + 1);
        row.setArtifactUrl(artifactUrl == null || artifactUrl.isBlank() ? null : artifactUrl.trim());
        row.setMetadataPayload(metadata == null || metadata.isNull() ? null : requireObject(metadata, "metadata").toString());
        row.setStatus(PublishStatus.DRAFT);
        stampCreator(row::setCreatedBy, row::setCreatedByName);
        row.setCreatedAt(LocalDateTime.now());
        ModelVersion saved = modelRepository.save(row);
        auditService.userAction(AuditAction.MODEL_CREATE, "device", device.getDeviceCode(),
                "新增模型版本 " + name + " v" + saved.getVersion());
        return toView(saved);
    }

    public List<ModelView> models(Long deviceId, String modelName, int limit) {
        deviceLookupService.requireDevice(deviceId);
        PageRequest page = PageRequest.of(0, cap(limit));
        List<ModelVersion> rows = (modelName == null || modelName.isBlank())
                ? modelRepository.findByDeviceIdOrderByCreatedAtDesc(deviceId, page)
                : modelRepository.findByDeviceIdAndModelNameOrderByVersionDesc(deviceId, modelName.trim(), page);
        return rows.stream().map(PublishService::toView).toList();
    }

    public ModelView model(Long deviceId, String modelName, int version) {
        return toView(requireModel(deviceId, modelName, version));
    }

    public PublishResult publishModel(Long deviceId, String modelName, int version) {
        String name = requireName(modelName, "modelName");
        ModelVersion row = requireModel(deviceId, name, version);
        boolean rollback = version < modelRepository.findMaxVersion(deviceId, name);
        ObjectNode payload = mapper.createObjectNode();
        payload.put("modelName", name);
        payload.put("version", version);
        if (row.getArtifactUrl() == null) {
            payload.putNull("artifactUrl");
        } else {
            payload.put("artifactUrl", row.getArtifactUrl());
        }
        payload.set("metadata", parse(row.getMetadataPayload()));
        PublishResult result = dispatch(deviceId, CMD_MODEL, version, payload, rollback,
                AuditAction.MODEL_PUBLISH, "模型 " + name + " v" + version);
        if (!"FAILED".equals(result.commandResult()) && PublishStatus.DRAFT.equals(row.getStatus())) {
            row.setStatus(PublishStatus.PUBLISHED);
            modelRepository.save(row);
        }
        return withStatus(result, row.getStatus());
    }

    // ------------------------------------------------------------------ 策略

    public StrategyView createStrategy(String name, JsonNode payload) {
        String strategyName = requireName(name, "name");
        JsonNode body = requireObject(payload, "payload");
        ControlStrategy row = new ControlStrategy();
        row.setName(strategyName);
        row.setVersion(strategyRepository.findMaxVersion(strategyName) + 1);
        row.setStrategyPayload(body.toString());
        row.setStatus(PublishStatus.DRAFT);
        stampCreator(row::setCreatedBy, row::setCreatedByName);
        row.setCreatedAt(LocalDateTime.now());
        ControlStrategy saved = strategyRepository.save(row);
        auditService.userAction(AuditAction.STRATEGY_CREATE, "strategy", strategyName,
                "新增策略版本 " + strategyName + " v" + saved.getVersion());
        return toView(saved);
    }

    public List<StrategyView> strategies(String name, int limit) {
        PageRequest page = PageRequest.of(0, cap(limit));
        List<ControlStrategy> rows = (name == null || name.isBlank())
                ? strategyRepository.findAllByOrderByCreatedAtDesc(page)
                : strategyRepository.findByNameOrderByVersionDesc(name.trim(), page);
        return rows.stream().map(PublishService::toView).toList();
    }

    public StrategyView strategy(String name, int version) {
        return toView(requireStrategy(name, version));
    }

    public PublishResult publishStrategy(Long deviceId, String name, int version) {
        String strategyName = requireName(name, "name");
        ControlStrategy row = requireStrategy(strategyName, version);
        boolean rollback = version < strategyRepository.findMaxVersion(strategyName);
        ObjectNode payload = mapper.createObjectNode();
        payload.put("name", strategyName);
        payload.put("version", version);
        payload.set("strategy", parse(row.getStrategyPayload()));
        PublishResult result = dispatch(deviceId, CMD_STRATEGY, version, payload, rollback,
                AuditAction.STRATEGY_PUBLISH, "策略 " + strategyName + " v" + version);
        if (!"FAILED".equals(result.commandResult()) && PublishStatus.DRAFT.equals(row.getStatus())) {
            row.setStatus(PublishStatus.PUBLISHED);
            strategyRepository.save(row);
        }
        return withStatus(result, row.getStatus());
    }

    // ------------------------------------------------------------- 当前生效配置

    public PublishablesView publishables(Long deviceId) {
        Device device = deviceLookupService.requireDevice(deviceId);
        return activeForDevice(deviceId, device.getDeviceCode());
    }

    /** 边缘端 / 界面共用：这台设备当前 ACTIVE 的参数、策略与模型。 */
    public PublishablesView activeForDevice(Long deviceId, String deviceCode) {
        List<ControlParameter> parameters = parameterRepository.findByDeviceIdAndStatus(deviceId, PublishStatus.ACTIVE);
        List<ModelVersion> models = modelRepository.findByDeviceIdAndStatus(deviceId, PublishStatus.ACTIVE);
        List<ControlStrategy> strategies = strategyRepository.findByStatus(PublishStatus.ACTIVE);
        return new PublishablesView(deviceCode,
                parameters.isEmpty() ? null : toView(parameters.get(0)),
                strategies.stream().map(PublishService::toView).toList(),
                models.stream().map(PublishService::toView).toList(),
                LocalDateTime.now());
    }

    // ------------------------------------------------------------------ 回执

    /**
     * 边缘端回执成功后把对应版本置为 ACTIVE，并把同范围内旧的 ACTIVE 置为 SUPERSEDED。
     * 失败回执只记日志（详情在 command_log），版本状态保持 PUBLISHED 便于重发。
     */
    public void applyAck(CommandLog command) {
        try {
            if (command == null || !"SUCCESS".equalsIgnoreCase(command.getResult())) {
                return;
            }
            int version = command.getVersion() == null ? -1 : command.getVersion();
            if (version < 0) {
                return;
            }
            JsonNode payload = parse(command.getPayload());
            String kind = command.getCmdType();
            if (CMD_PARAMETER.equals(kind)) {
                parameterRepository.findByDeviceIdAndVersion(command.getDeviceId(), version)
                        .ifPresent(row -> activateParameter(row));
            } else if (CMD_MODEL.equals(kind)) {
                String name = text(payload, "modelName");
                if (name != null) {
                    modelRepository.findByDeviceIdAndModelNameAndVersion(command.getDeviceId(), name, version)
                            .ifPresent(row -> activateModel(row));
                }
            } else if (CMD_STRATEGY.equals(kind)) {
                String name = text(payload, "name");
                if (name != null) {
                    strategyRepository.findByNameAndVersion(name, version)
                            .ifPresent(row -> activateStrategy(row));
                }
            }
        } catch (Exception ex) {
            log.warn("failed to apply publish ack for command {}: {}", command.getMessageId(), ex.getMessage());
        }
    }

    private void activateParameter(ControlParameter row) {
        for (ControlParameter other : parameterRepository.findByDeviceIdAndStatus(row.getDeviceId(), PublishStatus.ACTIVE)) {
            if (!other.getId().equals(row.getId())) {
                other.setStatus(PublishStatus.SUPERSEDED);
                parameterRepository.save(other);
            }
        }
        row.setStatus(PublishStatus.ACTIVE);
        parameterRepository.save(row);
        auditService.deviceAction(AuditAction.PARAMETER_APPLIED, deviceCode(row.getDeviceId()), "parameter",
                String.valueOf(row.getVersion()), "参数 v" + row.getVersion() + " 已在设备生效", "SUCCESS");
    }

    private void activateModel(ModelVersion row) {
        for (ModelVersion other : modelRepository.findByDeviceIdAndStatus(row.getDeviceId(), PublishStatus.ACTIVE)) {
            if (!other.getId().equals(row.getId()) && other.getModelName().equals(row.getModelName())) {
                other.setStatus(PublishStatus.SUPERSEDED);
                modelRepository.save(other);
            }
        }
        row.setStatus(PublishStatus.ACTIVE);
        modelRepository.save(row);
        auditService.deviceAction(AuditAction.MODEL_APPLIED, deviceCode(row.getDeviceId()), "model",
                row.getModelName() + ":" + row.getVersion(),
                "模型 " + row.getModelName() + " v" + row.getVersion() + " 已在设备生效", "SUCCESS");
    }

    private void activateStrategy(ControlStrategy row) {
        for (ControlStrategy other : strategyRepository.findByStatus(PublishStatus.ACTIVE)) {
            if (!other.getId().equals(row.getId()) && other.getName().equals(row.getName())) {
                other.setStatus(PublishStatus.SUPERSEDED);
                strategyRepository.save(other);
            }
        }
        row.setStatus(PublishStatus.ACTIVE);
        strategyRepository.save(row);
        auditService.deviceAction(AuditAction.STRATEGY_APPLIED, "cloud", "strategy",
                row.getName() + ":" + row.getVersion(),
                "策略 " + row.getName() + " v" + row.getVersion() + " 已在设备生效", "SUCCESS");
    }

    // ------------------------------------------------------------------ 内部

    private PublishResult dispatch(Long deviceId, String kind, int version, JsonNode payload, boolean rollback,
                                   String auditAction, String label) {
        Device device = deviceLookupService.requireDevice(deviceId);
        CommandLog command = commandService.dispatch(deviceId, new CommandRequest(kind, version, payload));
        boolean pushed = !"FAILED".equals(command.getResult());
        String detail = (rollback ? "回滚下发 " : "下发 ") + label + " → " + device.getDeviceCode()
                + " messageId=" + command.getMessageId();
        if (pushed) {
            auditService.userAction(auditAction, "device", device.getDeviceCode(), detail);
        } else {
            auditService.userFailure(auditAction, "device", device.getDeviceCode(), detail, command.getResultDetail());
        }
        return new PublishResult(kind, version, command.getMessageId(), PublishStatus.PUBLISHED,
                command.getResult(), rollback);
    }

    private static PublishResult withStatus(PublishResult result, String status) {
        return new PublishResult(result.kind(), result.version(), result.messageId(), status,
                result.commandResult(), result.rollback());
    }

    private ControlParameter requireParameter(Long deviceId, int version) {
        deviceLookupService.requireDevice(deviceId);
        return parameterRepository.findByDeviceIdAndVersion(deviceId, version)
                .orElseThrow(() -> new IllegalArgumentException("参数版本不存在：" + deviceId + " v" + version));
    }

    private ModelVersion requireModel(Long deviceId, String modelName, int version) {
        deviceLookupService.requireDevice(deviceId);
        return modelRepository.findByDeviceIdAndModelNameAndVersion(deviceId, requireName(modelName, "modelName"), version)
                .orElseThrow(() -> new IllegalArgumentException("模型版本不存在：" + modelName + " v" + version));
    }

    private ControlStrategy requireStrategy(String name, int version) {
        return strategyRepository.findByNameAndVersion(requireName(name, "name"), version)
                .orElseThrow(() -> new IllegalArgumentException("策略版本不存在：" + name + " v" + version));
    }

    private static void stampCreator(java.util.function.Consumer<Long> idSetter,
                                     java.util.function.Consumer<String> nameSetter) {
        CurrentUser user = CurrentUserService.current().orElse(null);
        if (user != null) {
            idSetter.accept(user.id());
            nameSetter.accept(user.username());
        }
    }

    private String deviceCode(Long deviceId) {
        try {
            return deviceLookupService.requireDevice(deviceId).getDeviceCode();
        } catch (RuntimeException ex) {
            return String.valueOf(deviceId);
        }
    }

    private static int cap(int limit) {
        return Math.min(Math.max(limit, 1), MAX_LIST);
    }

    private static String requireName(String value, String field) {
        String trimmed = value == null ? "" : value.trim();
        if (!NAME_PATTERN.matcher(trimmed).matches()) {
            throw new IllegalArgumentException(field + " 只能是字母/数字/下划线/短横线/点，长度 1-64：" + value);
        }
        return trimmed;
    }

    private static JsonNode requireObject(JsonNode payload, String field) {
        if (payload == null || payload.isNull() || !payload.isObject()) {
            throw new IllegalArgumentException(field + " 必须是 JSON 对象");
        }
        return payload;
    }

    private JsonNode parse(String json) {
        if (json == null || json.isBlank()) {
            return mapper.createObjectNode();
        }
        try {
            return mapper.readTree(json);
        } catch (Exception ex) {
            log.warn("failed to parse stored publish payload: {}", ex.getMessage());
            return mapper.createObjectNode();
        }
    }

    private static String text(JsonNode node, String field) {
        if (node == null) {
            return null;
        }
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asText();
    }

    private static ParameterView toView(ControlParameter row) {
        return new ParameterView(row.getId(), row.getDeviceId(), row.getVersion(), readPayload(row.getParamPayload()),
                row.getStatus(), row.getCreatedBy(), row.getCreatedByName(), row.getCreatedAt());
    }

    private static StrategyView toView(ControlStrategy row) {
        return new StrategyView(row.getId(), row.getName(), row.getVersion(), readPayload(row.getStrategyPayload()),
                row.getStatus(), row.getCreatedBy(), row.getCreatedByName(), row.getCreatedAt());
    }

    private static ModelView toView(ModelVersion row) {
        return new ModelView(row.getId(), row.getDeviceId(), row.getModelName(), row.getVersion(),
                row.getArtifactUrl(), readPayload(row.getMetadataPayload()), row.getStatus(),
                row.getCreatedBy(), row.getCreatedByName(), row.getCreatedAt());
    }

    private static JsonNode readPayload(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return JSON.readTree(json);
        } catch (Exception ex) {
            return null;
        }
    }
}