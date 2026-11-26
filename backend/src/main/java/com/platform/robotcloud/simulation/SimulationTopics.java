package com.platform.robotcloud.simulation;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 边端（simulation 契约）的 topic 约定：{@code simulation/{simulationId}/{suffix}}。
 * <p>与 robot 契约（{@code robot/{deviceCode}/{suffix}}）并存，见 {@code docs/mqtt-contract.md}。
 */
public final class SimulationTopics {

    private static final Pattern STATE = Pattern.compile("^simulation/([^/]+)/state$");
    private static final Pattern HEARTBEAT = Pattern.compile("^simulation/([^/]+)/heartbeat$");
    private static final Pattern COMMAND_ACK = Pattern.compile("^simulation/([^/]+)/command_ack$");
    private static final Pattern EXPERIMENT_RUN = Pattern.compile("^simulation/([^/]+)/experiment_run$");
    private static final Pattern EXPERIMENT_EVENT = Pattern.compile("^simulation/([^/]+)/experiment_event$");

    private SimulationTopics() {
    }

    /** topic 是 simulation/{id}/state 时返回 simulationId，否则 null。 */
    public static String simulationIdFromState(String topic) {
        return extract(STATE, topic);
    }

    /** topic 是 simulation/{id}/heartbeat 时返回 simulationId，否则 null。 */
    public static String simulationIdFromHeartbeat(String topic) {
        return extract(HEARTBEAT, topic);
    }

    /** topic 是 simulation/{id}/command_ack 时返回 simulationId，否则 null。 */
    public static String simulationIdFromCommandAck(String topic) {
        return extract(COMMAND_ACK, topic);
    }

    /** topic 是 simulation/{id}/experiment_run 时返回 simulationId，否则 null。 */
    public static String simulationIdFromExperimentRun(String topic) {
        return extract(EXPERIMENT_RUN, topic);
    }

    /** topic 是 simulation/{id}/experiment_event 时返回 simulationId，否则 null。 */
    public static String simulationIdFromExperimentEvent(String topic) {
        return extract(EXPERIMENT_EVENT, topic);
    }

    private static String extract(Pattern pattern, String topic) {
        if (topic == null) {
            return null;
        }
        Matcher matcher = pattern.matcher(topic);
        return matcher.matches() ? matcher.group(1) : null;
    }
}