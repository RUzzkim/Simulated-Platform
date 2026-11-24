package com.platform.robotcloud.mqtt;

import org.eclipse.paho.client.mqttv3.IMqttAsyncClient;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.integration.annotation.ServiceActivator;
import org.springframework.integration.channel.DirectChannel;
import org.springframework.integration.mqtt.core.ClientManager;
import org.springframework.integration.mqtt.outbound.MqttPahoMessageHandler;
import org.springframework.integration.mqtt.support.DefaultPahoMessageConverter;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.MessageHandler;

/**
 * 下行通道与入站共用同一个 ClientManager（一条连接），避免同 clientId 互相踢线。
 */
@Configuration
public class MqttOutboundConfig {

    @Bean
    public MessageChannel mqttOutboundChannel() {
        return new DirectChannel();
    }

    @Bean
    @ServiceActivator(inputChannel = "mqttOutboundChannel")
    public MessageHandler mqttOutbound(
            ClientManager<IMqttAsyncClient, MqttConnectOptions> mqttClientManager) {
        MqttPahoMessageHandler handler = new MqttPahoMessageHandler(mqttClientManager);
        handler.setAsync(true);
        handler.setDefaultQos(1);
        handler.setConverter(new DefaultPahoMessageConverter());
        return handler;
    }
}