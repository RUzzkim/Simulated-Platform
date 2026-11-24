package com.platform.robotcloud.mqtt;

import javax.net.ssl.KeyManager;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManagerFactory;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;

/**
 * 用 PEM 格式的 CA 证书构建 SSLSocketFactory，供自签 CA 的 MQTT TLS 连接使用，
 * 这样不必给 JVM 预置 truststore。
 *
 * <p>broker 打开 require_certificate true（阶段 4 的双向认证）后，客户端也要出示证书：
 * 这里额外支持 PKCS12 客户端密钥库（含证书链与私钥），由 MQTT_CLIENT_KEYSTORE 指定。
 */
public final class MqttTlsSupport {

    private MqttTlsSupport() {
    }

    public static SSLSocketFactory socketFactory(String caCertPath) {
        return socketFactory(caCertPath, null, null);
    }

    public static SSLSocketFactory socketFactory(String caCertPath, String clientKeystorePath,
                                                 String clientKeystorePassword) {
        try {
            TrustManagerFactory trustManagerFactory = trustManagerFactory(caCertPath);
            KeyManager[] keyManagers = keyManagers(clientKeystorePath, clientKeystorePassword);
            SSLContext context = SSLContext.getInstance("TLS");
            context.init(keyManagers, trustManagerFactory.getTrustManagers(), null);
            return context.getSocketFactory();
        } catch (Exception ex) {
            throw new IllegalStateException("failed to build MQTT TLS socket factory from " + caCertPath, ex);
        }
    }

    private static TrustManagerFactory trustManagerFactory(String caCertPath) throws Exception {
        try (InputStream in = Files.newInputStream(Path.of(caCertPath))) {
            Certificate ca = CertificateFactory.getInstance("X.509").generateCertificate(in);
            KeyStore keyStore = KeyStore.getInstance(KeyStore.getDefaultType());
            keyStore.load(null, null);
            keyStore.setCertificateEntry("mqtt-ca", ca);
            TrustManagerFactory trustManagerFactory =
                    TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            trustManagerFactory.init(keyStore);
            return trustManagerFactory;
        }
    }

    private static KeyManager[] keyManagers(String clientKeystorePath, String password) throws Exception {
        if (clientKeystorePath == null || clientKeystorePath.isBlank()) {
            return null;
        }
        char[] secret = password == null ? new char[0] : password.toCharArray();
        KeyStore keyStore = KeyStore.getInstance("PKCS12");
        try (InputStream in = Files.newInputStream(Path.of(clientKeystorePath))) {
            keyStore.load(in, secret);
        }
        KeyManagerFactory keyManagerFactory =
                KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        keyManagerFactory.init(keyStore, secret);
        return keyManagerFactory.getKeyManagers();
    }
}