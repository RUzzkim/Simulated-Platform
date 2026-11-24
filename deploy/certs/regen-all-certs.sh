#!/bin/sh
# 一次性重生成整套证书（修复 CA 重复扩展导致 Java 后端 MQTT TLS 崩溃的问题）。
# 在服务器 /root/platform/deploy/certs 目录，用 alpine/openssl 容器跑：
#   docker run --rm --entrypoint sh -v /root/platform/deploy/certs:/certs -w /certs alpine/openssl /certs/regen-all-certs.sh
#
# 产物：ca.{crt,key} + server.{crt,key} + cloud-service.{crt,key,p12}
#       + edge/edge-robot-001.{crt,key,p12} + edge/edge-SIM-001.{crt,key,p12}
# CA 用显式 openssl-ca.cnf（扩展只写一次），Java 21 严格解析器可读。
set -e
cd /certs

CLIENT_PASS="${MQTT_CLIENT_KEYSTORE_PASSWORD:-robot-cloud-client}"
EDGE_PASS="${EDGE_KEYSTORE_PASSWORD:-robot-cloud-edge}"
DAYS="${CERT_DAYS:-825}"

echo "== 1/5 CA (显式 config, 扩展单次) =="
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout ca.key -out ca.crt -config openssl-ca.cnf

echo "== 2/5 server (SAN 覆盖公网 IP 106.15.43.100) =="
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=robot-cloud-dev"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days "$DAYS" -sha256 -extfile openssl-san.cnf -extensions v3_req
rm -f server.csr ca.srl

echo "== 3/5 cloud-service (后端 MQTT 客户端, CN=cloud-service) =="
openssl req -newkey rsa:2048 -nodes -keyout cloud-service.key -out cloud-service.csr -subj "/CN=cloud-service"
openssl x509 -req -in cloud-service.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out cloud-service.crt -days "$DAYS" -sha256 -extfile openssl-client.cnf -extensions client_req
openssl pkcs12 -export -inkey cloud-service.key -in cloud-service.crt \
  -out cloud-service.p12 -name cloud-service -passout pass:"$CLIENT_PASS"
rm -f cloud-service.csr ca.srl

echo "== 4/5 edge 客户端证书 (CN=deviceCode) =="
mkdir -p edge
for dev in robot-001 SIM-001; do
  base="edge/edge-$dev"
  openssl req -newkey rsa:2048 -nodes -keyout "$base.key" -out "$base.csr" -subj "/CN=$dev"
  openssl x509 -req -in "$base.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "$base.crt" -days "$DAYS" -sha256 -extfile openssl-client.cnf -extensions client_req
  openssl pkcs12 -export -inkey "$base.key" -in "$base.crt" \
    -out "$base.p12" -name "$dev" -passout pass:"$EDGE_PASS"
  rm -f "$base.csr" ca.srl
  chmod 644 "$base.crt"; chmod 640 "$base.key" "$base.p12"
done

echo "== 5/5 权限 =="
chmod 644 ca.crt server.crt cloud-service.crt
chmod 640 ca.key server.key cloud-service.key cloud-service.p12

echo "== 校验：ca.crt 扩展应各出现一次（无 Duplicate）=="
openssl x509 -in ca.crt -noout -text | grep -A1 'X509v3'
echo "== 校验：server SAN 应含 106.15.43.100 =="
openssl x509 -in server.crt -noout -text | grep -A1 'Subject Alternative Name'
echo "done."
