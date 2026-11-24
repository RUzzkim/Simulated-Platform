# MQTT 通信契约

## Topic 规划

| Topic | 方向 | 说明 |
|---|---|---|
| `robot/{deviceId}/telemetry` | 边缘 → 云 | 周期遥测，建议 1–10 Hz |
| `robot/{deviceId}/heartbeat` | 边缘 → 云 | 边缘心跳，建议 5–10 s |
| `robot/{deviceId}/event` | 边缘 → 云 | 故障/告警事件 |
| `robot/{deviceId}/cmd` | 云 → 边缘 | 参数、策略、模型、配置下发 |
| `robot/{deviceId}/cmd_ack` | 边缘 → 云 | 下发执行回执 |
| `simulation/{simulationId}/state` | 边端 → 云 | 机械臂状态，10 Hz（simulation 契约，见下节） |
| `simulation/{simulationId}/heartbeat` | 边端 → 云 | 边端心跳，5 s |
| `simulation/{simulationId}/command` | 云 → 边端 | 运动指令 `START/STOP/MOVE_HOME/MOVE_JOINT` |
| `simulation/{simulationId}/command_ack` | 边端 → 云 | 指令回执，`command_log` 靠它置 `SUCCESS/FAILED` |
| `simulation/{simulationId}/config` | 云 → 边端 | 边端运行时配置（字段待定义） |
| `simulation/{simulationId}/sim_state` | 端 → 边（节点内） | 无 ROS 2 模式下仿真端的原始关节状态（边-端内部，云端不订阅） |

## 报文格式

统一 **严格 JSON**：时间用 ISO-8601 UTC，所有报文包含 `messageId`。

> ⚠️ 字段名必须带双引号。写成 `{deviceId:robot-001,...}` 这种伪 JSON 会被云端判为坏报文丢弃（只记一条 WARN，不影响其它报文）。

### telemetry

```json
{
  "messageId": "b1c2d3e4-0000-0000-0000-000000000001",
  "deviceId": "robot-001",
  "timestamp": "2026-01-01T00:00:00Z",
  "state": "RUNNING",
  "controlMode": "ADAPTIVE",
  "joints": [{ "name": "joint_1", "position": 0.0, "velocity": 0.0, "effort": 0.0 }],
  "endEffector": { "x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0 }
}
```

### heartbeat

```json
{
  "messageId": "b1c2d3e4-0000-0000-0000-000000000002",
  "deviceId": "robot-001",
  "timestamp": "2026-01-01T00:00:00Z",
  "status": "ONLINE",
  "cpu": 12.5,
  "memory": 40.0,
  "edgeVersion": "0.1.0"
}
```

### event

```json
{
  "messageId": "b1c2d3e4-0000-0000-0000-000000000003",
  "deviceId": "robot-001",
  "timestamp": "2026-01-01T00:00:00Z",
  "type": "TORQUE_ABNORMAL",
  "level": "WARNING",
  "detail": "joint_2 力矩异常",
  "context": { "joint": "joint_2", "torque": 3.7 }
}
```

### cmd / cmd_ack

```json
{
  "messageId": "b1c2d3e4-0000-0000-0000-000000000004",
  "deviceId": "robot-001",
  "timestamp": "2026-01-01T00:00:00Z",
  "cmdType": "PARAMETER",
  "version": 1,
  "payload": { "kp": 1.2 }
}
```

`cmdType` 由云端写入，边缘端按它分发。阶段 4 起有三种版本化下发（均可来自 `POST /api/devices/{id}/commands`，或来自「下发中心」的 `/publish` 接口）：

| `cmdType` | `payload` 形状 | 说明 |
|---|---|---|
| `PARAMETER` | 控制器参数对象，如 `{"kp":1.2,"ki":0.05}` | 按**设备**版本化 |
| `STRATEGY` | 策略对象，如 `{"mode":"ADAPTIVE","gains":{...}}` | 按**名字**全局版本化，可下发到任意设备 |
| `MODEL` | 模型元数据，如 `{"modelName":"torque-nn","artifactUrl":"...","metadata":{...}}` | 按**设备 + 模型名**版本化 |

`version` 是版本号，`payload` 是该版本的完整内容——边缘端**不需要自己维护版本**，把收到的 payload 应用即可。

```json
{
  "messageId": "b1c2d3e4-0000-0000-0000-000000000004",
  "deviceId": "robot-001",
  "timestamp": "2026-01-01T00:00:00Z",
  "result": "SUCCESS",
  "detail": "applied"
}
```

回执用 `messageId` 关联 `command_log`（兼容字段 `cmdId`）。

**回执决定版本状态**（版本状态机）：

| 回执 `result` | 云端动作 |
|---|---|
| `SUCCESS` | 该版本 → `ACTIVE`，同范围原来的 `ACTIVE` → `SUPERSEDED` |
| 其它（`FAILED`/`REJECTED`…） | **状态不变**（停在 `PUBLISHED`），`command_log.resultDetail` 记失败原因，可直接重发 |

所以边缘端必须回 `cmd_ack`，否则版本永远停在 `PUBLISHED`（不会生效）。回执既能走 MQTT `cmd_ack`，也能走 HTTP `POST /api/edge/cmd-ack`。

**对齐接口**：边缘端启动/断线重连后，用 edge token 拉 `GET /api/edge/publishables` 拿到本设备当前 `ACTIVE` 的参数、策略、模型（回执成功才算生效），与实时下发的 `cmd` 互补。

## 边端 simulation 契约（两族 topic 并存）

上面那套 `robot/{deviceCode}/*` 是本项目**自研边缘端**的契约；对接的边端节点（`Backend/edge_node`，Python + paho-mqtt）用的是 `simulation/{simulationId}/*`，**两族 topic 并存**。云端按 topic 前缀分流，归一化后写同一套表：

- `robot/` 前缀 → 原有的 telemetry/heartbeat/event/cmd_ack 处理链；
- `simulation/` 前缀 → `simulation` 适配层（`EdgeContractAdapter` 归一化后交给同一套 `TelemetryService` / `HeartbeatService`）。

身份是 **simulationId（`SIM-001`）+ robotId（`ROBOT-001`）**：一个仿真实例挂 N 个机械臂，一个边节点 = 一个仿真 + 一个机械臂。云端把 `robotId` 落到 `device.device_code`，`simulationId` 记在 `device.simulation_id`（边端首次上报时自动绑定）。

> ⚠️ `device_code` 必须是**大小写敏感**的 `utf8mb4_bin`：库默认的 `utf8mb4_0900_ai_ci` 会把边端的 `ROBOT-001` 和演示设备的 `robot-001` 判成同一台，两个数据源静默混在一台设备里。迁移见 `docs/migrate-v4-simulation.sql`。

### state（边端 → 云，10 Hz）

```json
{
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "timestamp": 1760000000123,
  "jointPosition": [0.11, 0.22, 0.33, 0.44, 0.55, 0.66],
  "jointVelocity": [0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
  "jointTorque": [1.1, 2.2, 3.3, 4.4, 5.5, 6.6],
  "status": "RUNNING",
  "faults": []
}
```

- `timestamp` 是 **13 位 Unix 毫秒**（不是 ISO-8601）。云端 `Payloads.fromEpoch` 按 `Payloads.PLATFORM_ZONE`（即容器 TZ，默认 `Asia/Shanghai`）换算成**北京时间墙钟**入库，与 ISO 分支、以及各处 `LocalDateTime.now()` 同一口径——边端发真实 epoch 即可。2026-09-19 之前落库的是 UTC 墙钟，已由 `docs/migrate-v6-local-time.sql` 整体 +8 小时对齐。
- 单位：`jointPosition` rad、`jointVelocity` rad/s、`jointTorque` N·m；三个数组固定 **6** 个，禁止改长度。
- `status` ∈ `RUNNING | STOPPED | ERROR`。
- 归一化后写 `telemetry_data`：`joints[{name:"joint_1".."joint_6", position, velocity, effort}]`（`jointTorque` → `effort`），前端曲线/故障统计直接复用。

### faults（v1.1 加法字段）

`faults[]` 表示**该帧的活动故障**（不是事件流）：有故障带 1 条，恢复正常就是 `[]`。

```json
{ "faultType": "TORQUE_OVERLOAD", "jointIndex": 1, "severity": "ERROR", "timestamp": 1760000001123, "detail": "joint_2 torque 48.6 Nm exceeds limit 40.0" }
```

- `faultType` ∈ `TORQUE_OVERLOAD | JOINT_LOCKED | VELOCITY_ANOMALY | SENSOR_INVALID | COMMUNICATION_TIMEOUT`；`severity` ∈ `WARNING | ERROR | CRITICAL`；`jointIndex` 0-based（通信类为 -1）。
- 字段每帧重复，云端 `SimulationFaultTracker` 做**边沿检测**：只在故障**出现**时插一条 `fault_event`（按 `deviceId|faultType|jointIndex` 去重），故障消失时在该条 `detail` 追加「（已恢复，持续 Ns）」，**不会每帧写一条**。
- `fault_event.contextPayload` 记 `{robotId, simulationId, jointIndex}`，便于在全局故障列表里区分来源。

### heartbeat（边端 → 云，5 s）

```json
{ "simulationId": "SIM-001", "robotId": "ROBOT-001", "timestamp": 1760000005123, "status": "ONLINE" }
```

`status` ∈ `ONLINE | OFFLINE`。
⚠️ 边端**遗嘱消息**（异常断线由 broker 代发）里 `robotId` 是**空串**、`timestamp` 是 0：云端认不出设备，**直接跳过并计数**（WARN + `unattributed`），不会凭空建一条空设备。

### command（云 → 边端）

```json
{
  "commandId": "8628493d-fd2f-4e7f-9267-4b3191d5cf3e",
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "cmdType": "MOVE_JOINT",
  "timestamp": 1789818265623,
  "jointTarget": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
  "speed": 0.5
}
```

- `cmdType` ∈ `START | STOP | MOVE_HOME | MOVE_JOINT`；`MOVE_JOINT` 必带 6 个 `jointTarget`；`speed` ∈ [0, 5]。
- **报文只有这 7 个字段**：边端 `RobotCommand.from_dict` 只读这些，**不要塞 `messageId` / `version` / `payload`**（云端 `SimulationCommand` 已保证）。
- `commandId` 与 `command_log.message_id` 取同一个 UUID，边端将来补 ack 时可直接对账。
- 下发入口仍是 `POST /api/devices/{id}/commands`：设备绑定了 `simulationId`（即边端）就走这条通道，否则走原来的 `robot/{deviceCode}/cmd`。对边端设备下发非运动类 `cmdType`（如 `STRATEGY`）会被**明确拒绝**（400），不会静默发进没人订阅的主题。
- 执行完立刻回执到 `simulation/{simId}/command_ack`：`{commandId, simulationId, robotId, cmdType, result, detail, timestamp}`，`commandId` 就是云端 `message_id`（`CommandService.recordAck` 会依次认 `messageId`/`cmdId`/`commandId`），回执到达后 `command_log.result` 从 `PENDING` 变 `SUCCESS/FAILED` 并写入 `acknowledgedAt`。

### 边端侧现状

1. **TLS 已支持**：`_parse_broker` 认 `ssl://` / `mqtts://` / `tls://`（默认端口 8883），建连时 `tls_set(ca_certs, certfile, keyfile)`，默认校验服务端主机名（`tls_insecure` 仅供联调）。
2. **broker 与证书**：`edge_config.yaml` 的 `broker_url: "ssl://<云端>:8883"`，证书 `edge_node/certs/` 下 `ca.crt` + `edge-SIM-001.{crt,key}`（路径相对配置文件目录解析）；broker 是双向认证，`username/password` 留空即可。
3. **回执已补**（见上）。
4. 遗嘱消息仍带空 `robotId`（云端跳过并计数），属已知项，不影响数据入库。

## 投递语义与速率

- 订阅端（云端）以 **QoS 1** 订阅四个上报 topic，设备按 QoS 1 上报即可；实际 QoS 取收发两端较小值，所以设备**必须用 QoS 1**，用 QoS 0 会在突发时静默丢帧。
- 坏报文只丢当前帧：`MqttMessageRouter` 兜底所有异常并计数（`GET /api/system/stats` → `mqttRouter.malformedDropped`）。**任何一条脏报文都不会像以前那样打断云端 MQTT 连接**。
- 设备侧脚本建议一条消息一次连接（`mock-edge.ps1` 的写法），或保持 ≤ 1–10 Hz 的稳态速率。用 `mosquitto_pub -l -q 1` 一次性从文件灌几百上千条时，**是 mosquitto_pub 客户端自己会在中途断链并静默结束**（不是 broker 或云端丢帧）；批量压测请分块发布（每块 100 条、独立连接），或直接用 QoS 0 做纯吞吐冒烟。

## 账号与 ACL

- 禁止匿名连接（`allow_anonymous false`），**每台设备一个独立账号**，账号名 = 设备编号（如 `robot-001`）。
- 阶段 4 起 broker 打开**双向认证**（`require_certificate true` + `use_identity_as_username true`）：客户端必须出示 CA 签发的证书，**用户名直接取证书 CN**，所以签发的 CN 必须等于设备编号，才能命中 `aclfile` 里的 `user <deviceCode>`。实测：不带证书连接会被 TLS 拒绝（`peer did not return a certificate`）；用 `CN=robot-001` 的证书连接，broker 日志里记录的用户名就是 `robot-001`。
  - 证书签发：`server/issue-edge-cert.ps1 -DeviceCode robot-001`（产物 `deploy/certs/edge/edge-<code>.{crt,key,p12}`，拷到边缘端）。
  - 开启双向认证后 `passwordfile` 对带证书的客户端不再起作用，只作兜底（同一份 aclfile 仍然生效）。
  - 云端后端自己也持证书（`deploy/certs/cloud-service.p12`，CN=`cloud-service`），见 `MQTT_CLIENT_KEYSTORE`。
- ACL 最小权限：
  - 云端服务账号 `cloud-service`：读 `robot/+/telemetry|heartbeat|event|cmd_ack`，写 `robot/+/cmd`；**边端**这条链路读 `simulation/+/state|heartbeat`、写 `simulation/+/command`。
  - 边节点 `user <simulationId>`（如 `SIM-001`）：写 `simulation/SIM-001/state|heartbeat|command_ack`、读写 `simulation/SIM-001/sim_state`（无 ROS 2 模式下本机仿真端复用同一张证书）、读 `simulation/SIM-001/command|config`；另外**还可以写** `simulation/SIM-001/command`——容错时它把 `MOVE_JOINT_SAFE` 发回同一主题给仿真端，属边-端内部协议（边端会跳过自己发出的 `EDGE-SAFE-*`，避免自环报错）。
  - 边端证书：`server/issue-edge-cert.ps1 -DeviceCode SIM-001`（**CN 必须 = simulationId**）；ACL 里的 `user SIM-001` 由 `provision-mqtt.ps1 -Simulations SIM-001` 写入，设备还没上报过也能先写。
  - 每台设备：只读 `robot/<自己的编号>/cmd`，只写自己的 `telemetry/heartbeat/event/cmd_ack`。
  - 实测：设备账号发别人的 topic 会被丢弃；设备账号无法读遥测（拿不到别的设备数据）。
- 账号密码与 edge token 由云端签发，见 `GET/POST /api/devices/{id}/credentials`（设备详情页「边缘接入」卡片）。
- 把凭据写到 broker 上（生成 `passwordfile` + `aclfile` 并热加载）：

  ```powershell
  $env:ADMIN_PASSWORD = "admin-local-pass"
  ..\server\provision-mqtt.ps1
  ```

  脚本会登录云端 → 逐台读取凭据 → 用一次性的 `mosquitto_passwd` 容器写 `deploy/mosquitto/passwordfile` → 生成 `deploy/mosquitto/aclfile` → `docker cp` 进容器 + `chown` + `SIGHUP` 重载。
  注意 `mosquitto.conf` 里的 `password_file`/`acl_file` 指向容器内 `/mosquitto/conf/*`（启动时从 `/mosquitto/config` 拷的副本），所以只改宿主机文件不生效，必须走这个脚本（或手工 `docker cp` + 重载）。

## 安全策略

- 只开放 TLS 监听：`listener 8883` + `tls_version tlsv1.2`（实际协商 TLSv1.2/1.3），明文 1883 已关闭；生产环境公网只暴露 443/8883。
- **边端也必须走 TLS**：`simulation/*` 与 `robot/*` 用的是同一个 broker（8883 只开 TLS），边端连 `tcp://:1883` 会直接连不上；边端已改用 `ssl://` + 客户端证书，见上文「边端侧现状」。
- 端口约定：容器内 8883，本地联调宿主机映射 `127.0.0.1:8884`，生产直接映射 8883。
- 边缘端与云端都必须校验服务端证书（**双向认证**：服务端同时也校验客户端证书），自签 CA 用法：
  - 客户端：`mosquitto_sub/pub -h <host> -p 8883 --cafile ca.crt --cert edge-<device>.crt --key edge-<device>.key`（`-u/-P` 已可省略）。
  - 后端：`MQTT_BROKER=ssl://mqtt:8883` + `MQTT_CA_CERT=/certs/ca.crt`（PEM 格式 CA；留空则用 JVM 默认信任库）。
  - 禁止在生产使用 `--insecure`、跳过校验或信任所有证书。
- 证书签发与 SAN 列表见 `deploy/certs/generate-certs.sh`、`deploy/certs/openssl-san.cnf`；SAN 必须覆盖边缘端连接的域名或 IP，换域名/IP 后要重新签发。
- 阶段 4 已启用**客户端证书双向认证**：`mosquitto.conf` 里 `require_certificate true` + `use_identity_as_username true`。
  - 云端后端：`MQTT_CLIENT_KEYSTORE=/certs/cloud-service.p12` + `MQTT_CLIENT_KEYSTORE_PASSWORD`（PKCS12，含证书链与私钥），配合 `MQTT_CA_CERT` 校验 broker。
  - 边缘端：`--cafile ca.crt --cert edge-<code>.crt --key edge-<code>.key`（或用 `.p12`），**不再需要 `-u/-P`**。
  - 证书私钥本身就是凭据：`.key` 权限 600/640，泄露等同设备口令泄露，按同样级别保管与轮换。
- 指令下发必须来自云端服务账号，并记录审计日志。
- 订阅端（云端后端）短时跟不上时，broker 默认只缓存 1000 条就会丢；`deploy/mosquitto/mosquitto.conf` 已放宽到 `max_queued_messages 10000`、`max_inflight_messages 40`。