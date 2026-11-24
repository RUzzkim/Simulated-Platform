package com.platform.robotcloud.command;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;

import java.util.List;

/**
 * 下发指令请求（一个入口，两族设备）。
 * <ul>
 *   <li>robot 契约（本项目原生）：{@code cmdType} + 自由 {@code payload}，走 robot/{deviceCode}/cmd；</li>
 *   <li>simulation 契约（边端）：{@code cmdType} ∈ START/STOP/MOVE_HOME/MOVE_JOINT，
 *       MOVE_JOINT 必须给 6 个 {@code jointTarget}，{@code speed} 取 [0,5]，走 simulation/{simulationId}/command。</li>
 * </ul>
 * 走哪条分支由设备是否绑定了 simulationId 决定，前端不必显式指定。
 */
public record CommandRequest(@NotBlank String cmdType,
                             Integer version,
                             JsonNode payload,
                             List<Double> jointTarget,
                             Double speed) {

    /**
     * robot 契约的旧调用点（发布策略/模型/配置）用这个：只给 cmdType + payload。
     * <p>这类指令打到边端设备上会被 SimulationCommand 拒绝（边端只认四个运动指令），
     * 报错总比把 robot/xxx/cmd 发进无人订阅的主题、界面显示「已下发」要好。
     */
    public CommandRequest(String cmdType, Integer version, JsonNode payload) {
        this(cmdType, version, payload, null, null);
    }
}