# 端-边对接包（连接云端 broker）

> 面向：边端节点（`edge_node`，Python paho-mqtt）与仿真端负责人。
> 云端已上线到公网 ECS，本文件给出连上生产 broker 所需的全部信息。
> 更新日期：2026-09-21（证书本日重新签发，旧证书作废，需重新分发）。

## 1. 连接参数

| 项 | 值 |
|---|---|
| Broker 地址 | `ssl://106.15.43.100:8883`（仅 TLS，明文 1883 关闭） |
| 协议 | MQTT v3.1.1，QoS 统一 **1** |
| 认证方式 | **双向 TLS**：客户端必须出示 CA 签发的证书；用户名自动取证书 CN，`username/password` 留空 |
| TLS 版本 | TLSv1.2 / 1.3（客户端别降到 tlsv1.0/1.1，broker 会拒） |
| 主机名校验 | **开启**，别用 `--insecure`。服务端证书 SAN 已含 `106.15.43.100`，用这个 IP 连即可 |

> ⚠️ 安全组：公网访问需云端在阿里云控制台放行 **8883**（MQTT）与 **443**（前端 HTTPS）。若连不上先确认这步已做。

## 2. 证书清单（云端签发，本日 2026-09-21 重签）

在云端 `deploy/certs/` 下，按角色取对应文件分发（`.key` 是私钥，等同口令，600/640 保管、勿进 git）：

| 角色 | 文件 | CN | 说明 |
|---|---|---|---|
| 通用信任根 | `certs/ca.crt` | robot-cloud-dev-ca | 所有客户端都要，用作 `--cafile` |
| 边端（自研 robot 链路） | `certs/edge/edge-robot-001.{crt,key,p12}` | robot-001 | CN=设备编号 |
| 仿真边端（simulation 链路） | `certs/edge/edge-SIM-001.{crt,key,p12}` | SIM-001 | **CN=simulationId** |

- `.p12` 口令：`EDGE_KEYSTORE_PASSWORD`（默认 `robot-cloud-edge`），给不方便用 PEM 的客户端。
- **旧证书作废**：2026-09-21 之前拿到的 edge 证书是旧 CA 签的，已全部失效，必须换这批新的。

分发方式（云端执行，示例取 SIM-001）：
```bash
cd /root/platform/deploy/certs
# 打包该边端所需三件：CA + 自己的证书私钥
tar czf /tmp/edge-SIM-001-bundle.tar.gz ca.crt -C edge edge-SIM-001.crt edge-SIM-001.key
# 再从云端 scp/下载到边端机器；私钥务必走安全通道
```

## 3. 边端配置（edge_node）

> ⚠️ **待边端核对**：下方 `mqtt.tls` 的字段名（`ca_cert`/`cert_file`/`key_file` 等）尚未与
> `edge_node/config/edge_config.yaml` 及 `mqtt_client.py` 的 `tls_set` 实际读取的键名逐一核对，
> 仅为占位示意。以边端代码实际字段名为准，请边端同学确认后再填。

需要设置的**值**（字段名以边端配置为准）：
- broker：`ssl://106.15.43.100:8883`（边端 `_parse_broker` 认 `ssl:// / mqtts:// / tls://`）
- `username / password`：留空（双向 TLS 下不需要）
- CA：`ca.crt`；客户端证书：`edge-SIM-001.crt`；私钥：`edge-SIM-001.key`（路径相对配置文件目录解析）
- TLS insecure：保持关闭（生产不跳过主机名校验）
- 身份：`edge.simulation_id = "SIM-001"`、`edge.robot_id = "ROBOT-001"`

把 `ca.crt` 与 `edge-SIM-001.{crt,key}` 放进 `edge_node/certs/`。client_id 为 `edge-node-<simulationId>`，同仿真多实例必须改。

## 4. Topic 与报文契约

以边端 simulation 链路为准（详见 `docs/mqtt-contract.md` §「边端 simulation 契约」与 `edge/edge_node/docs/edge_cloud_integration.md`）：

| # | 方向 | Topic | 频率 | 载荷 |
|---|---|---|---|---|
| 1 | 边 → 云 | `simulation/{simId}/state` | 10Hz | RobotState（timestamp 为 13 位 Unix 毫秒） |
| 2 | 边 → 云 | `simulation/{simId}/heartbeat` | 5s | Heartbeat（ONLINE/OFFLINE） |
| 3 | 云 → 边 | `simulation/{simId}/command` | 事件 | RobotCommand（START/STOP/MOVE_HOME/MOVE_JOINT） |
| 4 | 边 → 云 | `simulation/{simId}/command_ack` | 事件 | 回执，决定 command_log 置 SUCCESS/FAILED |

要点（易踩）：
- **严格 JSON**，字段名带双引号、camelCase；`timestamp` 是 13 位毫秒（不是 ISO-8601）。
- 关节三数组固定 **6** 个：`jointPosition`(rad) / `jointVelocity`(rad/s) / `jointTorque`(N·m→云端存 effort)。
- 运动指令只认 `START/STOP/MOVE_HOME/MOVE_JOINT`；`MOVE_JOINT` 必带 6 个 `jointTarget`，`speed`∈[0,5]。
- command 报文只有 7 个字段，别塞 `messageId/version/payload`。
- 必须回 `command_ack`（`commandId` = 云端 message_id），否则指令版本停在 PENDING 不生效。
- 用 QoS 1；QoS 0 突发会静默丢帧。

## 5. 连通性自测（拿到证书后先跑这个）

```bash
# 订阅自己的 state（能连上且不报 TLS 错就算通）
mosquitto_sub -h 106.15.43.100 -p 8883 \
  --cafile ca.crt --cert edge-SIM-001.crt --key edge-SIM-001.key \
  -t 'simulation/SIM-001/state' -q 1 -v

# 发一帧 heartbeat 试写权限
mosquitto_pub -h 106.15.43.100 -p 8883 \
  --cafile ca.crt --cert edge-SIM-001.crt --key edge-SIM-001.key \
  -t 'simulation/SIM-001/heartbeat' -q 1 \
  -m '{"simulationId":"SIM-001","robotId":"ROBOT-001","timestamp":1760000000000,"status":"ONLINE"}'
```

- 连上无 TLS 报错 = 证书链 + 主机名校验通过。
- 报 `peer did not return a certificate` = 没带 `--cert/--key`。
- 报 `tlsv1 alert protocol version` = 客户端 TLS 版本太低，升到 1.2+。
- 报连接超时 = 安全组 8883 没放行，或 IP/端口写错。

## 6. HTTPS 通道（凭据/对齐接口）

- 前端/管理：`https://106.15.43.100/`（443）。
- 边端拉当前生效配置：`GET /api/edge/publishables`（带 edge token）。
- edge token 与设备凭据：设备详情页「边缘接入」卡片，或 `GET /api/devices/{id}/credentials`。
