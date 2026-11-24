package com.platform.robotcloud.simulation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 把边端的 simulation 契约报文归一化成云端内部模型（robot 契约），
 * 让下游的批量入库 / 归档 / 降采样 / 前端一行都不用改。
 *
 * <table>
 *   <tr><th>边端</th><th>云端内部</th></tr>
 *   <tr><td>robotId (ROBOT-001)</td><td>deviceId / device_code</td></tr>
 *   <tr><td>timestamp（Unix 毫秒）</td><td>timestamp（原样透传，Payloads 认数字）</td></tr>
 *   <tr><td>status (RUNNING/STOPPED/ERROR)</td><td>state</td></tr>
 *   <tr><td>jointPosition[]/jointVelocity[]/jointTorque[]</td><td>joints[{name,position,velocity,effort}]</td></tr>
 * </table>
 */
@Component
public class EdgeContractAdapter {

    private final ObjectMapper mapper = new ObjectMapper();

    /** 边端 state → 云端 telemetry 载荷。 */
    public ObjectNode toTelemetry(JsonNode edge) {
        ObjectNode out = mapper.createObjectNode();
        out.put("deviceId", robotId(edge));
        // timestamp 原样透传：Payloads.reportedAt 对数字节点走 epoch 分支
        out.set("timestamp", edge.path("timestamp"));
        String status = text(edge, "status");
        if (status != null) {
            out.put("state", status);
        }
        out.set("joints", joints(edge));
        return out;
    }

    /** 边端 heartbeat → 云端 heartbeat 载荷（cpu/memory/edgeVersion 边端不产生，留空）。 */
    public ObjectNode toHeartbeat(JsonNode edge) {
        ObjectNode out = mapper.createObjectNode();
        out.put("deviceId", robotId(edge));
        out.set("timestamp", edge.path("timestamp"));
        out.put("status", text(edge, "status") == null ? "ONLINE" : text(edge, "status"));
        return out;
    }

    /** 边端 state 里随帧携带的活动故障明细，缺失时返回空列表。 */
    public List<JsonNode> faults(JsonNode edge) {
        JsonNode node = edge.path("faults");
        if (!node.isArray()) {
            return List.of();
        }
        List<JsonNode> result = new ArrayList<>(node.size());
        node.forEach(result::add);
        return result;
    }

    /**
     * 三个长度 6 的数组 → joints 对象数组。
     * <p>关节名用 1 基下标（jointPosition[0] → joint_1），与云端既有的
     * mock-edge / 前端曲线命名保持一致。
     */
    private ArrayNode joints(JsonNode edge) {
        JsonNode position = edge.path("jointPosition");
        JsonNode velocity = edge.path("jointVelocity");
        JsonNode torque = edge.path("jointTorque");
        int count = Math.max(position.size(), Math.max(velocity.size(), torque.size()));
        ArrayNode joints = mapper.createArrayNode();
        for (int i = 0; i < count; i++) {
            ObjectNode joint = joints.addObject();
            joint.put("name", "joint_" + (i + 1));
            joint.put("position", position.path(i).asDouble(0));
            joint.put("velocity", velocity.path(i).asDouble(0));
            joint.put("effort", torque.path(i).asDouble(0));
        }
        return joints;
    }

    /** robotId；空串或缺失都返回 null（边端的遗嘱报文 robotId 是空串）。 */
    public static String robotId(JsonNode edge) {
        return text(edge, "robotId");
    }

    private static String text(JsonNode json, String field) {
        JsonNode node = json.path(field);
        if (node.isMissingNode() || node.isNull()) {
            return null;
        }
        String value = node.asText().trim();
        return value.isEmpty() ? null : value;
    }
}