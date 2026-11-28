package com.platform.robotcloud.mqtt;

import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.integration.channel.DirectChannel;
import org.springframework.integration.core.MessageProducer;
import org.eclipse.paho.client.mqttv3.IMqttAsyncClient;
import org.springframework.integration.mqtt.core.ClientManager;
import org.springframework.integration.mqtt.core.Mqttv3ClientManager;
import org.springframework.integration.mqtt.inbound.MqttPahoMessageDrivenChannelAdapter;
import org.springframework.integration.mqtt.support.DefaultPahoMessageConverter;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.MessageHandler;
import org.springframework.integration.annotation.ServiceActivator;

@Configuration
public class MqttInboundConfig {

    @Value("${mqtt.broker}")
    private String broker;

    @Value("${mqtt.username}")
    private String username;

    @Value("${mqtt.password}")
    private String password;

    @Value("${mqtt.client-id}")
    private String clientId;

    @Value("${mqtt.ca-cert:}")
    private String caCert;

    /** 双向认证：PKCS12 客户端密钥库（含证书与私钥），留空表示不出示客户端证书 */
    @Value("${mqtt.client-keystore:}")
    private String clientKeystore;

    @Value("${mqtt.client-keystore-password:}")
    private String clientKeystorePassword;

    @Bean
    public MessageChannel mqttInputChannel() {
        return new DirectChannel();
    }

    @Bean
    public ClientManager<IMqttAsyncClient, MqttConnectOptions> mqttClientManager() {
        MqttConnectOptions options = new MqttConnectOptions();
        options.setServerURIs(new String[] { broker });
        options.setUserName(username);
        options.setPassword(password.toCharArray());
        options.setCleanSession(true);
        options.setAutomaticReconnect(true);
        if (caCert != null && !caCert.isBlank()) {
            // 自签 CA 场景：直接信任指定的 PEM CA 证书；配了客户端密钥库就是双向认证
            options.setSocketFactory(MqttTlsSupport.socketFactory(caCert, clientKeystore, clientKeystorePassword));
        }
        Mqttv3ClientManager manager = new Mqttv3ClientManager(options, clientId);
        return manager;
    }

    @Bean
    public MessageProducer mqttInbound(
            MessageChannel mqttInputChannel,
            ClientManager<IMqttAsyncClient, MqttConnectOptions> mqttClientManager) {
        MqttPahoMessageDrivenChannelAdapter adapter =
                new MqttPahoMessageDrivenChannelAdapter(
                        mqttClientManager,
                        "robot/+/telemetry",
                        "robot/+/heartbeat",
                        "robot/+/event",
                        "robot/+/cmd_ack",
                        // 边端（simulation 契约）的上报主题，载荷由 simulation 包归一化后入库
                        "simulation/+/state",
                        "simulation/+/heartbeat",
                        "simulation/+/command_ack",
                        // V2 实验 Run 与故障/决策事件（契约 2.0.0）
                        "simulation/+/experiment_run",
                        "simulation/+/experiment_event");
        adapter.setOutputChannel(mqttInputChannel);
        adapter.setCompletionTimeout(5000);
        adapter.setConverter(new DefaultPahoMessageConverter());
        adapter.setQos(1);
        return adapter;
    }

    @Bean
    @ServiceActivator(inputChannel = "mqttInputChannel")
    public MessageHandler edgeMessageRouter(MqttMessageRouter router) {
        return router;
    }
}