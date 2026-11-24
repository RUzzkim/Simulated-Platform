# 云端部署说明

1. 先完成 `docs/dev-plan.md` 的服务器检查，确认 Broker 现状与端口占用。
2. 复制 `.env.example` 为 `.env`，填写 MySQL 与 MQTT 密码，并**必须**显式提供（生产 compose 全部用 `${VAR:?}`，缺失直接拒绝启动）：
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD`：首次启动时创建的管理员账号（密码要强随机）。
   - `JWT_SECRET`：用户与 edge token 的签名密钥，≥32 字节随机串。
   - `CREDENTIAL_KEY`：设备 MQTT 密码/edge token 的 AES-256-GCM 加密密钥。
   - `EDGE_BROKER_HOST` / `EDGE_BROKER_PORT`：回填给边缘端的 broker 地址（生产 `8883`；本地联调是 `127.0.0.1` + `8884`）。
   - `MQTT_CLIENT_KEYSTORE_PASSWORD`：`certs/cloud-service.p12` 的口令（云端后端自己的客户端证书，双向认证用），必须与第 4 步生成证书时用的值一致。
   - 三个密钥改动后，旧令牌与已签发凭据全部失效，需要重新签发并重跑 `server/provision-mqtt.ps1`。
3. 生成 Mosquitto 密码文件：`docker run --rm -v $PWD/mosquitto:/mosquitto/config eclipse-mosquitto:2 mosquitto_passwd -c /mosquitto/config/passwordfile cloud-service`。
   - 生产建议直接用 `server/provision-mqtt.ps1`：它按云端签发的凭据生成 `passwordfile` 与**严格 ACL 的 `aclfile`**（每台设备只读写自己的 topic），并热加载 broker。
   - **服务器（Linux）上这么跑**：容器名和入口都跟本地不同，三个参数必须显式给，否则会打到没有映射的 `8443` 和不存在的 `robot-mosquitto-local`（脚本只告警，ACL 不会更新，表现为「设备能连上但收不到消息」）：`pwsh ./server/provision-mqtt.ps1 -BaseUrl http://127.0.0.1:8082 -Container robot-mosquitto -DeployDir /root/platform/deploy -Simulations SIM-001`。前提是服务器装了 PowerShell 7（`pwsh`）与 `curl`；`-BaseUrl` 用 `https://127.0.0.1/`（443，自签）也行，脚本内部带 `-k`。
4. 生成本环境证书：`docker run --rm --entrypoint sh -v $PWD/certs:/certs -w /certs alpine/openssl /certs/generate-certs.sh /certs 825`（Windows 用 `.\certs\generate-dev-certs.ps1`）。
   - 产物 `certs/ca.crt`、`certs/ca.key`、`certs/server.crt`、`certs/server.key`，以及**云端客户端证书** `certs/cloud-service.{crt,key,p12}`（CN=`cloud-service`，口令取自 `MQTT_CLIENT_KEYSTORE_PASSWORD`）；`*.key`/`*.p12` 是私钥，不要提交或外发。
   - `certs/openssl-san.cnf` 里的 SAN 必须覆盖边缘端实际连接的域名或 IP，改了要重新生成。
   - **每台设备**再签发一张客户端证书：`server\issue-edge-cert.ps1 -DeviceCode <设备编号>` → `deploy/certs/edge/edge-<编号>.{crt,key,p12}`，拷到边缘端。CN 必须等于设备编号（broker 用 `use_identity_as_username` 把 CN 当用户名，去命中 aclfile 的 `user <deviceCode>`）。
   - **边端节点（simulation 契约）**：证书 CN = **simulationId**（如 `SIM-001`）：`server\issue-edge-cert.ps1 -DeviceCode SIM-001`；并在跑 provision 时把它写进 ACL（设备还没上报过也不会漏）：`server\provision-mqtt.ps1 -Simulations SIM-001`（多个用逗号分隔）。
   - 边端拿到证书后的配置（`ssl://` + ca/cert/key）与「边端待改」清单见 `docs/mqtt-contract.md`。
5. **在宿主机已有的 `xinqing-mysql` 里建本项目专用库与账号**（本 compose 不自带 MySQL，复用共享实例）。红线：只在新库 `robot_cloud` 上操作，**绝不碰 `xinqing` 库、绝不 DROP、绝不删卷**；`robot` 账号只授权 `robot_cloud.*`（最小权限）。`<ROOT_PW>` 是 xinqing-mysql 的 root 口令，`<MYSQL_PASSWORD>` 必须与 `.env` 里 `MYSQL_PASSWORD` 一致（backend 用 `robot` 账号连它）。

   ```bash
   # 5.1 建库 + 建账号（账号用 '%' 因为 backend 走 docker 网络连，不是 localhost）
   docker exec -i xinqing-mysql mysql -uroot -p'<ROOT_PW>' <<'SQL'
   CREATE DATABASE IF NOT EXISTS robot_cloud DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER IF NOT EXISTS 'robot'@'%' IDENTIFIED BY '<MYSQL_PASSWORD>';
   GRANT ALL PRIVILEGES ON robot_cloud.* TO 'robot'@'%';
   FLUSH PRIVILEGES;
   SQL

   # 5.2 导入建表脚本（全库当前 schema，一次到位：已含 telemetry_hourly、device.status/simulation_id、
   #     command_log.acknowledged_at、app_user.status 等，全新库无需再跑任何 migrate-*.sql）
   docker exec -i xinqing-mysql mysql -uroot -p'<ROOT_PW>' robot_cloud < ../docs/database-schema.sql

   # 5.3 验证：应列出 device / telemetry_data / telemetry_hourly / command_log / app_user 等 12 张表
   docker exec -i xinqing-mysql mysql -uroot -p'<ROOT_PW>' -e "USE robot_cloud; SHOW TABLES;"
   ```

   - **全新库不跑 migration**：`docs/migrate-v*.sql` 都是给「已存在的旧库」升级用的增量 ALTER/UPDATE，新库导入 `database-schema.sql` 后表结构已是最新。只有在原地升级一个老 `robot_cloud` 库时，才按 `v2→v3→v4→v5→v6→v7` 顺序补跑缺的那几支（各支幂等）。
   - **管理员账号无需手工插**：backend 首次启动会按 compose 里的 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 自动建管理员（`status=APPROVED` 可直接登录）。改密后重启不会覆盖已存在的账号。
6. 将现有 Spring Boot 项目构建为 `robot-backend:latest`，Vue3 项目构建到 `frontend/dist`。
7. 在 `deploy` 目录执行 `docker compose up -d`（compose 通过外部网络 `xinqing_default` 用容器名 `xinqing-mysql` 直连 3306；若 `docker network ls` 里名字不同，改 compose 末尾 `networks.xinqing.name`）。
8. 边缘端公网接入：只连 `8883`，带 `--cafile ca.crt --cert edge-<编号>.crt --key edge-<编号>.key`（broker 已开 `require_certificate true`，不出示客户端证书连不上；身份来自证书 CN，`-u/-P` 可省略）。明文 `1883` 已关闭，公网只暴露 443/8883。
9. 生产确认 `ADMIN_SEED_DEMO_USERS=false`（默认就是 false，只有 `docker-compose.local.yml` 显式打开），否则会多出 `operator`/`viewer` 两个弱口令演示账号。

## HTTP 端口说明（本机 80 被占）

宿主机 `80` 被 `xinqing-frontend` 占用，本项目 nginx 映射到 `8082:80`（HTTP）+ `443:443`（HTTPS 入口）。公网没有域名和受信任证书，手机微信/QQ 内置浏览器无法绕过自签证书（点了继续访问也进不去），所以 `8082` 默认直接提供页面与 `/api` 反代；想恢复「80 只做 301 跳 HTTPS」，把 compose 上的 `NGINX_HTTP_REDIRECT` 设为 `1`——**但本机没有受信任证书时别开**，开了手机就彻底打不开，原因见下一节。若要让 `80` 也归本项目，需先与 `xinqing` 协调让出端口，非必要不动。

## 手机 / 微信打不开页面

2026-09-21 线上实测（阿里云 ECS，公网 IP `106.15.43.100`）：`http://<ip>:8082/` 返回 `301 → https://<ip>:443/`，而 `443` 上挂的是**自签证书**（`curl -k` 才能过）。这就是「电脑能开、手机打不开」的直接原因：微信 / QQ 内置浏览器不接受自签证书，也不会弹「继续访问」，页面直接打不开；PC 浏览器点一次「继续访问」就过去了。

排查顺序：

1. 看 `8082` 到底是直接供页面还是在跳转：`curl -sI http://<公网IP>:8082/ | head -5`。出现 `301` + `Location: https://...:443/` 就是跳转了。
2. 看跳转开关：`deploy/.env` 里 `NGINX_HTTP_REDIRECT` 应为 `0`（两个 compose 文件默认也是 `0`）。改完 `docker compose -f docker-compose.yml up -d --force-recreate nginx`。
3. 用手机**自带浏览器**（不是微信）开 `http://<公网IP>:8082/`：能开而微信不能 → 微信侧限制；两边都开不了 → 先看 nginx / backend 日志。

三条出路，按投入排序：

- **保持 http 直供（零成本）**：`NGINX_HTTP_REDIRECT=0`，手机走 `http://<公网IP>:8082/`。纯 IP 的 http 页面在微信里可能提示「非官方网页」，但能正常打开。注意登录口令与设备凭据会明文过公网，只适合演示。
- **域名 + 受信任证书（正规做法）**：域名解析到本机公网 IP，用 `acme.sh` 走 **DNS-01** 签发 Let's Encrypt 证书——`80` 被 `xinqing-frontend` 占着，**http-01 验证走不通**，只能 DNS-01（阿里云域名可用 `--dns dns_ali` + AccessKey 自动验证）。把证书覆盖成 `deploy/certs/server.crt` / `server.key`（`nginx/default.conf.template` 的 443 块读的就是这两个路径，模板不用改），再 `docker exec robot-nginx nginx -s reload`。之后手机用 `https://<域名>/`，微信可正常打开。注意大陆 ECS 上的域名需要**备案**，未备案的域名走 80/443 仍可能被运营商拦截。
- **内网穿透 / Cloudflare Tunnel（没域名时最快）**：`cloudflared tunnel --url http://127.0.0.1:8082` 直接给一个 `https://xxx.trycloudflare.com`，微信能打开，不用证书、不用备案。仅作临时演示。

无论走哪条，**都不要让 `8082` 跳到自签的 `443`**——那等于两条路都堵死。

## 上线后自检

- `GET /api/system/stats`（需要 Bearer token）：`telemetryWriter.dropped`/`failedFlushes` 应为 0 且不持续增长；`mqttRouter.malformedDropped` 如果持续增长，说明有设备在发坏报文，去修设备侧载荷。
- 角色抽查：`viewer` 不能写设备、`operator` 不能进 `/api/users`、edge token 不能访问 `/api/**` 管理接口（应 403/401）。
- ACL 抽查：用设备账号发别人 topic 应被丢弃；用 `cloud-service` 写 `robot/+/telemetry` 也应被丢弃。

## TLS 配置要点

- Nginx（`nginx/default.conf.template`）：80 只做 `301` 跳 HTTPS，443 起 `TLSv1.2 TLSv1.3` + 安全头；HTTPS 端口由 compose 注入（本地 8443、生产 443）。
- Mosquitto（`mosquitto/mosquitto.conf`）：只有 `listener 8883`，`tls_version tlsv1.2`，**`require_certificate true` + `use_identity_as_username true`（双向认证已启用）**；证书路径指向容器内 `/mosquitto/certs/*`。实测不带客户端证书会被拒（`peer did not return a certificate`）。
- Mosquitto 的 compose 启动命令会先把证书与账号文件从 `/mosquitto/config` 拷到 `/mosquitto/{certs,conf}` 并 `chown mosquitto`：mosquitto 启动后会丢掉补充组，直接读绑定挂载上 0600/0640 的私钥会失败。**改完 `mosquitto.conf`/`aclfile`/`passwordfile` 后必须让 broker 重新加载**（`provision-mqtt.ps1` 已包含 `SIGHUP`；改 `mosquitto.conf` 本体则需要 `up -d --force-recreate mqtt`），只改宿主机文件不会生效。
- 订阅端短时跟不上时 broker 默认只缓存 1000 条，已在 `mosquitto.conf` 放宽到 `max_queued_messages 10000` + `max_inflight_messages 40`。
- 后端：`MQTT_BROKER=ssl://mqtt:8883` + `MQTT_CA_CERT=/certs/ca.crt` + `MQTT_CLIENT_KEYSTORE=/certs/cloud-service.p12` + `MQTT_CLIENT_KEYSTORE_PASSWORD`（compose 挂载 `./certs/ca.crt` 与 `./certs/cloud-service.p12`），既用自签 CA 校验 broker 证书，也出示自己的客户端证书。
- 客户端必须校验服务端证书，生产禁止 `--insecure`/跳过校验。
- 证书私钥（`ca.key`、`server.key`、`cloud-service.key/.p12`、`edge-*.key/.p12`）等同口令，按凭据级别保管；`edge-*.key` 泄露只影响那一台设备，轮换就是重新签发 + 让设备换证书。

## 换证书/换域名后

1. 更新 `certs/openssl-san.cnf` 的 SAN，重新跑第 4 步生成证书。
2. 重建相关容器：`docker compose up -d --force-recreate mqtt nginx backend`。
3. 边缘端同步更新 `ca.crt`（若 CA 也重新生成）。
4. 若 CA 重新生成，**所有设备证书都要重新签发**（旧证书不再被新 CA 信任），并重跑 `server/provision-mqtt.ps1`。

## 双向认证自检

```bash
# 带设备证书：应成功（不传 -u，用户名来自证书 CN）
docker exec robot-mosquitto-local mosquitto_pub -h localhost -p 8883 \
  --cafile /mosquitto/config/certs/ca.crt \
  --cert /mosquitto/config/certs/edge/edge-robot-001.crt \
  --key  /mosquitto/config/certs/edge/edge-robot-001.key \
  -q 1 -t robot/robot-001/cmd -m ok
# 不带客户端证书：应失败（peer did not return a certificate）
docker exec robot-mosquitto-local mosquitto_pub -h localhost -p 8883 \
  --cafile /mosquitto/config/certs/ca.crt -t test -m x
```
