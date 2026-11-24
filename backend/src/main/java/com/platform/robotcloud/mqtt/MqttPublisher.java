package com.platform.robotcloud.mqtt;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.integration.mqtt.support.MqttHeaders;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Component;

/**
 * 云端下行发布入口，统一走 mqttOutboundChannel。
 */
@Component
public class MqttPublisher {

    private final MessageChannel mqttOutboundChannel;

    public MqttPublisher(@Qualifier("mqttOutboundChannel") MessageChannel mqttOutboundChannel) {
        this.mqttOutboundChannel = mqttOutboundChannel;
    }

    public void publish(String topic, String payload) {
        mqttOutboundChannel.send(MessageBuilder.withPayload(payload)
                .setHeader(MqttHeaders.TOPIC, topic)
                .build());
    }
}