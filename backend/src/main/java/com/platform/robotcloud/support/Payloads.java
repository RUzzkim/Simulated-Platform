package com.platform.robotcloud.support;

import com.fasterxml.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;

/**
 * MQTT 报文字段的容错读取工具：字段缺失或格式异常时回退默认值，避免整条消息被丢弃。
 */
public final class Payloads {

    /** >= 13 位按毫秒、>= 10 位按秒；再短就不是时间戳（当作脏数据回退当前时间）。 */
    private static final long EPOCH_MILLIS_FLOOR = 100_000_000_000L;
    private static final long EPOCH_SECONDS_FLOOR = 1_000_000_000L;

    /**
     * 平台统一时区。库里所有墙钟时间都按它写入，避免同一列混两种口径：
     * 既有的 ISO 分支和 epoch 分支以前都按 UTC 墙钟存，界面直接展示就比本地时间早 8 小时。
     */
    public static final ZoneId PLATFORM_ZONE = ZoneId.systemDefault();

    private Payloads() {
    }

    public static String deviceCode(JsonNode json) {
        return text(json, "deviceId", null);
    }

    public static String text(JsonNode json, String field, String fallback) {
        JsonNode node = json.path(field);
        if (node.isMissingNode() || node.isNull()) {
            return fallback;
        }
        String value = node.asText();
        return value.isBlank() ? fallback : value;
    }

    public static BigDecimal decimal(JsonNode json, String field) {
        JsonNode node = json.path(field);
        return node.isNumber() ? node.decimalValue() : null;
    }

    /**
     * 取报文里的 timestamp。两套契约都要认：
     * <ul>
     *   <li>robot 契约：ISO-8601 字符串，如 {@code 2026-01-01T00:00:00Z}</li>
     *   <li>simulation 契约（边端 RobotState / Heartbeat）：Unix 毫秒整数，如 {@code 1760000000123}</li>
     * </ul>
     * 数字节点直接按 epoch 处理，不走字符串往返：大整数被 Jackson 写成 {@code 1.76E12}
     * 这种科学计数法时，字符串里的 {@code E} 会让 ISO 解析失败并静默回退成服务器当前时间。
     */
    public static LocalDateTime reportedAt(JsonNode json) {
        JsonNode node = json.path("timestamp");
        if (node.isNumber()) {
            return fromEpoch(node.longValue());
        }
        return parseTimestamp(node.isMissingNode() || node.isNull() ? null : node.asText());
    }

    public static LocalDateTime parseTimestamp(String raw) {
        if (raw == null || raw.isBlank()) {
            return LocalDateTime.now();
        }
        LocalDateTime epoch = tryEpoch(raw);
        if (epoch != null) {
            return epoch;
        }
        try {
            return OffsetDateTime.parse(raw).atZoneSameInstant(PLATFORM_ZONE).toLocalDateTime();
        } catch (DateTimeParseException ignored) {
            // 继续尝试不带时区的写法
        }
        try {
            return LocalDateTime.parse(raw);
        } catch (DateTimeParseException ignored) {
            return LocalDateTime.now();
        }
    }

    /**
     * Unix 时间戳（秒或毫秒）→ 时间。
     * <p>按 {@link #PLATFORM_ZONE} 换算成平台墙钟，与 {@link #parseTimestamp} 的 ISO 分支、
     * 以及各处 {@code LocalDateTime.now()} 保持同一口径——边端发真实 epoch 即可，落库与界面一致。
     */
    public static LocalDateTime fromEpoch(long value) {
        if (value >= EPOCH_MILLIS_FLOOR) {
            return LocalDateTime.ofInstant(Instant.ofEpochMilli(value), PLATFORM_ZONE);
        }
        if (value >= EPOCH_SECONDS_FLOOR) {
            return LocalDateTime.ofInstant(Instant.ofEpochSecond(value), PLATFORM_ZONE);
        }
        return LocalDateTime.now();
    }

    /** 纯数字且位数像时间戳时才按 epoch 解析，其余返回 null 交给 ISO 分支。 */
    private static LocalDateTime tryEpoch(String raw) {
        String trimmed = raw.trim();
        if (trimmed.isEmpty() || trimmed.length() > 14) {
            return null;
        }
        for (int i = 0; i < trimmed.length(); i++) {
            if (!Character.isDigit(trimmed.charAt(i))) {
                return null;
            }
        }
        try {
            return fromEpoch(Long.parseLong(trimmed));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    public static String jsonOrNull(JsonNode json, String field) {
        JsonNode node = json.path(field);
        return (node.isMissingNode() || node.isNull()) ? null : node.toString();
    }
}