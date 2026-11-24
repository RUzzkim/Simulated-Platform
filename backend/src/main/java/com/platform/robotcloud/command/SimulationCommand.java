package com.platform.robotcloud.command;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.platform.robotcloud.device.Device;

import java.util.List;
import java.util.Set;

/**
 * simulation 契约（边端）的下行报文构造。
 * <p>边端 {@code RobotCommand.from_dict} 只读这 7 个字段：
 * {@code commandId / simulationId / robotId / cmdType / jointTarget / speed / timestamp}，
 * 所以这里绝不塞 messageId、version、payload 之类的字段——多出来的字段边端不会读，
 * 只会让两套契约在报文里混在一起，日后没法判断谁说了算。
 * <p>{@code commandId} 与 {@code command_log.message_id} 取同一个 UUID，
 * 将来边端补 ack（回传 commandId）时可以直接对账。
 */
final class SimulationCommand {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** 边端 model/messages.py 的 CMD_TYPE_SET，改动要与边端对齐。 */
    private static final Set<String> CMD_TYPES = Set.of("START", "STOP", "MOVE_HOME", "MOVE_JOINT");

    private static final String MOVE_JOINT = "MOVE_JOINT";

    private static final int JOINT_COUNT = 6;

    private static final double SPEED_MAX = 5.0;

    private SimulationCommand() {
    }

    /**
     * @param payload 记进 command_log.payload 的「指令参数」（jointTarget/speed），与 robot 契约一致；
     * @param body   真正发到 simulation/{simulationId}/command 的报文。
     */
    record Prepared(ObjectNode payload, ObjectNode body) {
    }

    static Prepared prepare(Device device, CommandRequest request, String commandId) {
        String cmdType = request.cmdType() == null ? "" : request.cmdType().trim().toUpperCase();
        if (!CMD_TYPES.contains(cmdType)) {
            throw new IllegalArgumentException(
                    "边端只认 START/STOP/MOVE_HOME/MOVE_JOINT，实际: " + request.cmdType());
        }

        ObjectNode payload = MAPPER.createObjectNode();
        ObjectNode body = MAPPER.createObjectNode();
        body.put("commandId", commandId);
        body.put("simulationId", device.getSimulationId());
        body.put("robotId", device.getDeviceCode());
        body.put("cmdType", cmdType);
        body.put("timestamp", System.currentTimeMillis());

        List<Double> target = request.jointTarget();
        if (target != null) {
            if (target.size() != JOINT_COUNT) {
                throw new IllegalArgumentException("jointTarget 长度必须为 " + JOINT_COUNT + "，实际: " + target.size());
            }
            ArrayNode joints = payload.putArray("jointTarget");
            for (int i = 0; i < target.size(); i++) {
                Double value = target.get(i);
                if (value == null || !Double.isFinite(value)) {
                    throw new IllegalArgumentException("jointTarget[" + i + "] 必须为有限数值");
                }
                joints.add(value);
            }
            body.set("jointTarget", joints.deepCopy());
        }
        if (MOVE_JOINT.equals(cmdType) && !body.has("jointTarget")) {
            throw new IllegalArgumentException("MOVE_JOINT 必须提供 " + JOINT_COUNT + " 个关节目标 jointTarget");
        }

        Double speed = request.speed();
        if (speed != null) {
            if (!Double.isFinite(speed) || speed < 0 || speed > SPEED_MAX) {
                throw new IllegalArgumentException("speed 必须在 [0, " + (int) SPEED_MAX + "] 范围内，实际: " + speed);
            }
            payload.put("speed", speed);
            body.put("speed", speed);
        }
        return new Prepared(payload, body);
    }
}