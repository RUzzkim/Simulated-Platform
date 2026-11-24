package com.platform.robotcloud.mqtt;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageHandler;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 把订阅到的消息按 topic 分发给对应的 EdgeMessageHandler。
 * <p>这里刻意吞掉所有异常：异常一旦抛回 Paho 的 CommsCallback，会让整条 MQTT 连接
 * 触发 Connection lost 并重连；而重连窗口内（cleanSession=true）设备上报的 QoS1
 * 报文会被 broker 直接丢掉。一条脏报文不能打挂整条上报链路，所以坏报文只记日志丢弃。
 */
@Component
public class MqttMessageRouter implements MessageHandler {

    public static final String TOPIC_HEADER = "mqtt_receivedTopic";

    private static final int SNIPPET_LIMIT = 200;

    private static final Logger log = LoggerFactory.getLogger(MqttMessageRouter.class);

    private final ObjectMapper mapper = new ObjectMapper();
    private final List<EdgeMessageHandler> handlers;
    private final AtomicLong malformedDropped = new AtomicLong();
    private final AtomicLong handlerFailed = new AtomicLong();

    public MqttMessageRouter(List<EdgeMessageHandler> discoveredHandlers) {
        this.handlers = List.copyOf(discoveredHandlers);
    }

    @Override
    public void handleMessage(Message<?> message) {
        String topic = message.getHeaders().get(TOPIC_HEADER, String.class);
        EdgeMessageHandler handler = resolve(topic);
        if (handler == null) {
            log.warn("No edge handler registered for topic {}", topic);
            return;
        }
        String raw = String.valueOf(message.getPayload());
        JsonNode payload;
        try {
            payload = mapper.readTree(raw);
        } catch (Exception ex) {
            long total = malformedDropped.incrementAndGet();
            log.warn("drop malformed payload on topic {} ({} dropped so far): {} | payload={}",
                    topic, total, ex.getMessage(), snippet(raw));
            return;
        }
        try {
            handler.handle(topic, payload);
        } catch (Exception ex) {
            long total = handlerFailed.incrementAndGet();
            log.error("failed to handle message on topic {} ({} failed so far): {} | payload={}",
                    topic, total, ex.getMessage(), snippet(raw));
        }
    }

    /** 坏报文 / 处理失败计数，供 /api/system/stats 观测。 */
    public record Stats(long malformedDropped, long handlerFailed) {
    }

    public Stats stats() {
        return new Stats(malformedDropped.get(), handlerFailed.get());
    }

    private static String snippet(String raw) {
        if (raw == null) {
            return "";
        }
        String flat = raw.replaceAll("\\s+", " ").trim();
        return flat.length() <= SNIPPET_LIMIT ? flat : flat.substring(0, SNIPPET_LIMIT) + "...";
    }

    private EdgeMessageHandler resolve(String topic) {
        if (topic == null) {
            return null;
        }
        for (EdgeMessageHandler handler : handlers) {
            if (handler.matches(topic)) {
                return handler;
            }
        }
        return null;
    }
}