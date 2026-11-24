#!/bin/sh
# 生成开发用自签 CA 与服务器证书（SAN 覆盖 localhost / mqtt / nginx / 127.0.0.1）
set -e
DIR=${1:-/certs}
DAYS=${2:-825}
cd "$DIR"

if [ ! -f ca.crt ]; then
  echo "creating dev CA ..."
  # 用显式 config 生成 CA，扩展只写一次。
  # 不用 -addext：某些 OpenSSL 3.x 构建（如 alpine/openssl 镜像）在 req -x509 时
  # 会把默认 openssl.cnf 的 x509_extensions 与 -addext 叠加，导致 basicConstraints/
  # keyUsage 出现两遍。宽松解析器能容忍，但 Java 21 严格解析器会抛
  # "Duplicate extensions not allowed"，使后端 MQTT TLS 工厂构建失败。
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout ca.key -out ca.crt -config openssl-ca.cnf
fi

openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=robot-cloud-dev"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days "$DAYS" -sha256 -extfile openssl-san.cnf -extensions v3_req
rm -f server.csr ca.srl

# 后端自己的客户端证书（broker 打开 require_certificate 后，云端连接也要出示证书）
# CN 必须与 aclfile 里的服务账号一致（cloud-service）
CLIENT_PASS=${MQTT_CLIENT_KEYSTORE_PASSWORD:-robot-cloud-client}
openssl req -newkey rsa:2048 -nodes -keyout cloud-service.key -out cloud-service.csr -subj "/CN=cloud-service"
openssl x509 -req -in cloud-service.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out cloud-service.crt -days "$DAYS" -sha256 -extfile openssl-client.cnf -extensions client_req
openssl pkcs12 -export -inkey cloud-service.key -in cloud-service.crt \
  -out cloud-service.p12 -name cloud-service -passout pass:"$CLIENT_PASS"
rm -f cloud-service.csr ca.srl
chmod 644 cloud-service.crt
chmod 640 cloud-service.key cloud-service.p12
echo "client keystore: cloud-service.p12 (password from MQTT_CLIENT_KEYSTORE_PASSWORD, default robot-cloud-client)"

# mosquitto 以非 root 用户运行：compose 启动时会把这些文件拷进容器内的 /mosquitto/{certs,conf} 并 chown
# 这里只保证权限合理：私钥不 world-readable
chmod 644 ca.crt server.crt
chmod 640 ca.key server.key

echo "done: ca.crt ca.key server.crt server.key cloud-service.{crt,key,p12} in $DIR"