#!/usr/bin/env bash
# 服务器初始化：在宿主机已有的 xinqing-mysql 里建 robot_cloud 库 + robot 账号、导入 schema、
# 落 mosquitto 账号文件、起 broker，最后做一遍 TLS/mTLS/ACL 自检。
# 红线：只动 robot_cloud 库，不 DROP、不碰 xinqing 库；deploy/.env 只补键、不整体覆盖。
set -euo pipefail

PROJECT_DIR="/root/platform"
MYSQL_CONTAINER="xinqing-mysql"
MQTT_CONTAINER="robot-mosquitto"
MQTT_USERNAME="cloud-service"

read -r -p "MySQL root password: " MYSQL_ROOT_PASSWORD
read -r -p "New MySQL robot password: " MYSQL_ROBOT_PASSWORD
read -r -p "MQTT cloud-service password: " MQTT_PASSWORD

echo "[1/6] Checking environment"
docker --version
docker compose version

echo "[2/6] Creating robot_cloud database and robot user"
docker exec -i "$MYSQL_CONTAINER" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE DATABASE IF NOT EXISTS robot_cloud DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'robot'@'%' IDENTIFIED BY '${MYSQL_ROBOT_PASSWORD}';
ALTER USER 'robot'@'%' IDENTIFIED BY '${MYSQL_ROBOT_PASSWORD}';
GRANT ALL PRIVILEGES ON robot_cloud.* TO 'robot'@'%';
FLUSH PRIVILEGES;
SQL

echo "[3/6] Importing database schema"
docker exec -i "$MYSQL_CONTAINER" mysql -uroot -p"$MYSQL_ROOT_PASSWORD" robot_cloud < "$PROJECT_DIR/docs/database-schema.sql"
docker exec -i "$MYSQL_CONTAINER" mysql -urobot -p"$MYSQL_ROBOT_PASSWORD" robot_cloud -e "SHOW TABLES;"

echo "[4/6] Checking deploy/.env (only fills missing keys, never overwrites)"
cd "$PROJECT_DIR/deploy"
if [ ! -f .env ]; then
  cat >&2 <<'MSG'
  deploy/.env 不存在。生产 compose 里每个键都是 ${VAR:?} 强制项，缺一个就拒绝启动。
  先 cp .env.example .env 并填好：
    MYSQL_PASSWORD                  必须与本步输入的 robot 口令一致
    MQTT_SERVICE_USERNAME/PASSWORD  云端服务账号
    ADMIN_USERNAME / ADMIN_PASSWORD 首次启动时建的管理员
    JWT_SECRET / CREDENTIAL_KEY     各 >=32 字节随机值
    MQTT_CLIENT_KEYSTORE_PASSWORD   必须与签 cloud-service.p12 时用的口令一致
    EDGE_BROKER_HOST                本机公网 IP 或域名；EDGE_BROKER_PORT=8883
    NGINX_HTTP_REDIRECT=0           8082 直供页面，不能跳自签的 443
  然后重跑本脚本。
MSG
  exit 1
fi
# 只补缺的键：整体重写会丢掉 JWT_SECRET / CREDENTIAL_KEY，旧令牌与已签发凭据会全部失效
for pair in "MYSQL_PASSWORD=${MYSQL_ROBOT_PASSWORD}" "MQTT_SERVICE_USERNAME=${MQTT_USERNAME}" "MQTT_SERVICE_PASSWORD=${MQTT_PASSWORD}"; do
  key="${pair%%=*}"
  if grep -q "^${key}=" .env; then
    echo "  .env already has ${key}, kept"
  else
    printf '%s\n' "$pair" >> .env
    echo "  .env wrote ${key}"
  fi
done
chmod 600 .env
grep -Fxq "MYSQL_PASSWORD=${MYSQL_ROBOT_PASSWORD}" .env || \
  echo "  警告：.env 里的 MYSQL_PASSWORD 与本次输入的 robot 口令不一致，backend 会连不上库" >&2
missing=""
for key in ADMIN_PASSWORD JWT_SECRET CREDENTIAL_KEY MQTT_CLIENT_KEYSTORE_PASSWORD EDGE_BROKER_HOST; do
  grep -q "^${key}=" .env || missing="${missing} ${key}"
done
if [ -n "$missing" ]; then
  echo "  deploy/.env 还缺：${missing}；补齐后再执行 docker compose up -d" >&2
  exit 1
fi

echo "[5/6] Generating Mosquitto password file and starting broker"
# 已有 passwordfile 时不能带 -c：mosquitto_passwd -c 在文件已存在时直接报错退出，
# 而且它会重建整个文件、把 provision-mqtt.ps1 写进去的设备账号全冲掉。只有文件不存在才用 -c。
PWFLAG=""
if [ ! -f "$PWD/mosquitto/passwordfile" ]; then PWFLAG="-c"; fi
docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b $PWFLAG /mosquitto/config/passwordfile "$MQTT_USERNAME" "$MQTT_PASSWORD"

docker compose up -d mqtt
docker ps --filter name="$MQTT_CONTAINER"

echo "[6/6] MQTT self-check (TLS 8883 / mTLS / ACL)"
CA=/mosquitto/certs/ca.crt
# 6.1 带 cloud-service 客户端证书：CN 命中 aclfile 的 user cloud-service，可写 robot/+/cmd
if docker exec "$MQTT_CONTAINER" mosquitto_pub -h localhost -p 8883 \
     --cafile "$CA" --cert /mosquitto/certs/cloud-service.crt --key /mosquitto/certs/cloud-service.key \
     -q 1 -t robot/setup-check/cmd -m '{"cmdType":"STOP"}'; then
  echo "  OK   证书链 + 主机名校验 + ACL 写 robot/+/cmd 都通过"
else
  echo "  FAIL 带客户端证书也发不出去，看 docker logs $MQTT_CONTAINER" >&2
  exit 1
fi
# 6.2 不带客户端证书：require_certificate true 下应被拒
if docker exec "$MQTT_CONTAINER" mosquitto_pub -h localhost -p 8883 --cafile "$CA" -t test -m x >/dev/null 2>&1; then
  echo "  FAIL 不带客户端证书竟然也发成功，require_certificate 没生效" >&2
  exit 1
else
  echo "  OK   不带客户端证书被拒（双向认证生效）"
fi
# 6.3 明文 1883 应已关闭
if docker exec "$MQTT_CONTAINER" mosquitto_pub -h localhost -p 1883 -t test -m x >/dev/null 2>&1; then
  echo "  FAIL 明文 1883 还能连上" >&2
  exit 1
else
  echo "  OK   明文 1883 已关闭"
fi

echo "Cloud setup complete."