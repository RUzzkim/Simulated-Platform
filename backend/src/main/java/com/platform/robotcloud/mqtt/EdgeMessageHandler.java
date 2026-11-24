package com.platform.robotcloud.mqtt;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * 处理某一类边缘上报 Topic 的载荷。
 * <p>两套 topic 契约并存：
 * <ul>
 *   <li>robot 契约（本项目原生）：{@code robot/{deviceCode}/{suffix}}</li>
 *   <li>simulation 契约（边端 RobotState/Heartbeat）：{@code simulation/{simulationId}/{suffix}}</li>
 * </ul>
 * 默认的 {@link #matches(String)} 只认 robot 契约，simulation 适配层的处理器覆写它做正则匹配，
 * 两族 topic 因此在构造上互不重叠（例如 {@code simulation/SIM-001/heartbeat} 不会被
 * robot 的 heartbeat 处理器抢走）。
 */
public interface EdgeMessageHandler {

    String topicSuffix();

    /**
     * 是否由本处理器负责该 topic。默认按 {@code robot/} 前缀 + 后缀匹配。
     */
    default boolean matches(String topic) {
        return topic != null && topic.startsWith("robot/") && topic.endsWith("/" + topicSuffix());
    }

    /**
     * 带 topic 的处理入口：topic 里可能带 payload 里没有的身份信息（如 simulationId）。
     */
    default void handle(String topic, JsonNode payload) throws Exception {
        handle(payload);
    }

    /**
     * 不带 topic 的处理入口。只按 topic 分发的处理器（simulation 适配层）覆写上面那个重载，
     * 不实现本方法。
     */
    default void handle(JsonNode payload) throws Exception {
        throw new UnsupportedOperationException(getClass().getSimpleName() + " 需要 topic 才能分发");
    }
}