package com.platform.robotcloud.analysis;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.platform.robotcloud.telemetry.TelemetryData;

/**
 * 遥测 joints 载荷的解析工具，供 analysis 包内各服务（趋势 / 下发效果）复用。
 *
 * <p>抽出来是为了不重复 {@link AnomalyService} 里那套 payload 遍历逻辑，也不动它、避免破坏
 * 第一批已上线的异常检测。每帧 jointPayload 是形如 {@code [{"name":..,"position":..,"velocity":..,"effort":..}]}
 * 的数组，脏帧静默跳过。
 */
final class JointMetrics {

    /** 支持的指标名，和边端契约（AI_RULES/schemas）一致。 */
    static final String[] METRICS = {"effort", "velocity", "position"};

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JointMetrics() {
    }

    /** 遍历一帧里每个关节的每个指标（值为数字才回调）。脏帧/空帧直接返回。 */
    static void forEach(TelemetryData frame, Consumer consumer) {
        JsonNode payload = parse(frame.getJointPayload());
        if (payload == null || !payload.isArray()) {
            return;
        }
        for (JsonNode joint : payload) {
            String name = joint.path("name").asText(null);
            if (name == null) {
                continue;
            }
            for (String metric : METRICS) {
                JsonNode node = joint.path(metric);
                if (node.isNumber()) {
                    consumer.accept(name, metric, node.asDouble());
                }
            }
        }
    }

    private static JsonNode parse(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return MAPPER.readTree(raw);
        } catch (Exception ex) {
            return null;
        }
    }

    static double round(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }

    @FunctionalInterface
    interface Consumer {
        void accept(String joint, String metric, double value);
    }

    /** 在线累计器：n / Σx / Σx² → 均值与总体标准差。与 AnomalyService 内同款，供复用。 */
    static final class Accumulator {
        private int n;
        private double sum;
        private double sumSq;

        void add(double value) {
            n++;
            sum += value;
            sumSq += value * value;
        }

        int count() {
            return n;
        }

        double mean() {
            return n == 0 ? 0 : sum / n;
        }

        double std() {
            if (n == 0) {
                return 0;
            }
            double mean = mean();
            double variance = Math.max(0, sumSq / n - mean * mean);
            return Math.sqrt(variance);
        }
    }
}
