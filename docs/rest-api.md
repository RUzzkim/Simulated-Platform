# REST API 规划与实现状态

接口前缀统一为 `/api`。图例：`[x]` 已实现、`[ ]` 待实现。

## 鉴权

除 `/api/auth/login` 与 `/api/health` 外，**所有接口都要求 `Authorization: Bearer <token>`**，两类令牌互不通用：

| 令牌 | 来源 | 权限 |
|---|---|---|
| 用户令牌 | `POST /api/auth/login` | ADMIN / OPERATOR / VIEWER，按角色限制 |
| 设备令牌（edge token） | `GET/POST /api/devices/{id}/credentials` | 只能访问 `/api/edge/**`，设备身份从令牌取 |

角色矩阵（实测）：

| 接口 | ADMIN | OPERATOR | VIEWER |
|---|---|---|---|
| `GET` 设备/遥测/故障 | 200 | 200 | 200 |
| `POST/PUT/PATCH/DELETE` 设备与指令 | 200 | 200 | 403 |
| `/api/users/**` 账号管理 | 200 | 403 | 403 |
| `GET /api/audit-logs` | 200 | 200 | 403 |
| `/api/devices/{id}/credentials` | 200 | 200 | 403 |
| 参数/策略/模型版本查询（`GET` `/api/devices/{id}/parameters`、`/models`、`/api/strategies` 等） | 200 | 200 | 200 |
| 参数/策略/模型新建与下发（同路径 `POST`，含 `/publish`） | 200 | 200 | 403 |
| `POST /api/system/archive`（遥测归档） | 200 | 403 | 403 |
| `/api/edge/**` | 403 | 403 | 403（只有 edge token 能访问） |

- 无令牌 → `401`；角色不足 → `403`；失败响应体统一为 `{"error":"..."}`。
- 用户令牌 TTL 默认 720 分钟（`JWT_USER_TTL_MINUTES`），edge token 默认 720 小时（`JWT_EDGE_TTL_HOURS`）。
- edge token 带 `tv`（token_version）：凭据轮换或吊销后，旧令牌立即失效。

## 认证与账号

- `[x]` `POST /api/auth/login`：`{username,password}` → `{token, expiresInMinutes, user{id,username,role,displayName,enabled,status,lastLoginAt}}`。仅 `status=APPROVED` 且启用的账号能登录；待审批 / 已驳回 / 已停用分别返回明确的 401 文案。
- `[x]` `POST /api/auth/register`（公开）：`{username,password,displayName?,role}` 自助注册，落库为 `status=PENDING` 且未启用，**不返回令牌**，需 ADMIN 审批后才能登录。`role` 为意向角色，最终以审批为准；用户名重复返回 400。
- `[x]` `GET /api/auth/me`：当前登录用户。
- `[x]` `POST /api/auth/password`：修改自己的密码（需登录）。
- `[x]` `GET /api/users`：账号列表（仅 ADMIN），含 `status` 审批状态字段。
- `[x]` `POST /api/users`：新建账号（仅 ADMIN），直接 `status=APPROVED` 可立即登录。
- `[x]` `POST /api/users/{id}/approve`：审批通过待审账号（仅 ADMIN），置 APPROVED 并启用，可选 `{role}` 顺带修正角色；非 PENDING 账号返回 400。
- `[x]` `POST /api/users/{id}/reject`：驳回待审账号（仅 ADMIN），置 REJECTED 并保持停用，账号保留以便审计。
- `[x]` `PUT /api/users/{id}`：改显示名/角色/启停（仅 ADMIN）；不允许停用或降级自己，也不允许移除最后一个（已批准且启用的）管理员。
- `[x]` `POST /api/users/{id}/password`：重置指定账号密码（仅 ADMIN）。

## 审计

- `[x]` `GET /api/audit-logs?action=&actor=&targetType=&page=&size=`：审计日志查询（ADMIN/OPERATOR）。
- `[x]` `GET /api/audit-logs/actions`：可选的 action 枚举，供前端下拉过滤。

已埋点的动作：登录成功/失败、改密、账号增改、自助注册/审批/驳回（`USER_REGISTER`/`USER_APPROVE`/`USER_REJECT`）、设备注册/重命名、指令下发/回执、凭据签发/查询/吊销、边缘事件上报，以及阶段 4 的 `PARAMETER_*` / `STRATEGY_*` / `MODEL_*`（新建 / 下发 / 生效）与 `TELEMETRY_ARCHIVE`。记录字段：`actorType`(USER/DEVICE/SYSTEM)、`actorName`、`action`、`targetType`、`targetId`、`detail`、`result`、`clientIp`、`createdAt`。

## 分析（健康评分 / 异常检测）

只读，任意已登录角色可看；纯计算跑在已有 telemetry_data / fault_event / device_heartbeat / command_log 上，无副作用、无新表。

- `[x]` `GET /api/analysis/health?windowHours=24`：机队健康总览，按综合分升序（最差在前）。每台返回 `score`(0-100)、`grade`(A≥90/B≥75/C≥60/D<60)、三分项 `availability`/`faultHealth`/`telemetryHealth`、`faultCounts`(按等级)、`topAnomalyJoints`(异常最多的前 3 关节)、`window`、`notes`。综合分 = 可用性×0.25 + 故障×0.35 + 遥测×0.40。
- `[x]` `GET /api/analysis/devices/{id}/health?windowHours=24`：单设备健康评估（字段同上单条）。
- `[x]` `GET /api/analysis/devices/{id}/anomalies?windowHours=24&sigma=3`（或显式 `from`/`to`）：遥测异常检测。对窗口内每关节 effort/velocity 建均值±kσ 基线，回扫标记越界样本。返回 `baselines`(每关节每指标 mean/std/lower/upper)、`points`(越界点，最多 500)、`framesScanned`、`sufficient`(≥30 帧)、`anomalyFrames`、`anomalyRatio`。语义是「相对设备自身近期基线的统计离群」，与边端规则式故障互补。
- `[x]` `GET /api/analysis/devices/{id}/trend?windowHours=24&buckets=12`（或显式 `from`/`to`）：趋势 / 预测性维护。对窗口内每关节 **effort** 等时间分桶取均值，最小二乘回归求斜率，用异常检测的基线上界（mean+3σ）当危险线外推。返回每关节 `slopePerHour`(单位/小时)、`current`(最近一桶均值)、`upperBound`、`hoursToUpper`(照此趋势到上界的小时数；斜率≤0 或已越界为 null)、`projection`(人话结论)、`sampleBuckets`(各桶均值，供画折线)。只做 effort（最能反映负载/磨损）。
- `[x]` `GET /api/analysis/commands/{commandId}/effect?metric=effort&windowMinutes=30`：下发效果分析。以该指令回执时刻（缺失则下发时刻）为界，对比前后各 `windowMinutes` 分钟内各关节 `metric`(默认 effort) 的均值/波动。返回 `before`/`after`(每关节 mean/std/samples)、`overallDelta`(加权均值变化)、`verdict`(人话结论：有效/无明显变化/样本不足)。把「下发—回执」与「遥测」两条线接成闭环证据。

## 设备

- `[x]` `GET /api/devices`：设备列表。
- `[x]` `GET /api/devices/{id}`：设备详情。
- `[x]` `GET /api/devices/{id}/status`：在线状态与最近心跳。
- `[x]` `GET /api/devices?status=&page=&size=`：状态过滤与分页（不传 page/size 时返回全量）。
- `[x]` `POST /api/devices`：注册设备（已存在则用新名称覆盖）。
- `[x]` `PUT /api/devices/{id}`：重命名设备，名称按 UTF-8 落库。

## 设备接入凭据（对接边和端）

- `[x]` `GET /api/devices/{id}/credentials`：查看已签发凭据（未签发时返回 `null`），含明文 MQTT 账号密码、edge token、broker 地址与可发布/可订阅 topic。
- `[x]` `POST /api/devices/{id}/credentials`：签发或轮换（`token_version` 递增，旧 edge token 立即失效）。
- `[x]` `DELETE /api/devices/{id}/credentials`：吊销（`REVOKED`，令牌失效；MQTT 账号在下次执行 `server/provision-mqtt.ps1` 后从 broker 移除）。

密码/令牌在库里用 AES-256-GCM 加密（密钥 `CREDENTIAL_KEY`），只有 ADMIN/OPERATOR 能读。

## 边缘 HTTP 上报通道

给只有 HTTP、不方便接 MQTT 的仿真端（Gazebo 桥接脚本等）使用；用 edge token 鉴权，报文 `deviceId` 与令牌不符直接 `403`。落库逻辑与 MQTT 通道完全一致。

- `[x]` `POST /api/edge/telemetry`、`POST /api/edge/heartbeat`、`POST /api/edge/event`：上报（`deviceId` 可省略，服务端按令牌补齐）。
- `[x]` `GET /api/edge/commands?limit=`：主动拉取本设备最近指令（MQTT 通道是订阅推送）。
- `[x]` `POST /api/edge/cmd-ack`：上报指令执行结果；若 `messageId` 属于别的设备则 `403`。
- `[x]` `GET /api/edge/me`：令牌身份与本设备的 topic 约定。
- `[x]` `GET /api/edge/publishables`：本设备当前应生效的参数/策略/模型（回执成功 = `ACTIVE`），边缘端启动或断线重连后拉一次即可与云端对齐（实时下发在 `/api/edge/commands` 里，两者互补）。

示例脚本：`server/mock-edge-http.ps1`。

## 遥测

- `[x]` `GET /api/devices/{id}/telemetry/latest`：最新一帧遥测。
- `[x]` `GET /api/devices/{id}/telemetry?page=&size=`：历史数据分页。
- `[x]` 时间范围过滤（`from`/`to`），区间内仍按 `reportedAt` 倒序分页。
- `[x]` `GET /api/devices/{id}/telemetry/series?from=&to=&limit=300&downsample=false`：历史曲线。
  `downsample=true` 时按**等时间分桶取均值**（桶内 `samples` = 原始帧数），点数上限 2000、原始扫描上限 20000 帧；`downsample=false` 时直接截断到 `limit` 最近的原始帧。
- `[x]` `GET /api/devices/{id}/telemetry/hourly?from=&to=`：归档小时桶（设备 + 小时，joints 为桶内均值，`frameCount` 为原始帧数）。

## 故障

- `[x]` `GET /api/fault-events?deviceId=&page=&size=`：故障列表。
- `[x]` `GET /api/fault-events/{id}`：故障详情。
- `[x]` `GET /api/fault-events/statistics?deviceId=&from=&to=`：按等级/类型/日期/设备统计，`deviceId` 省略即全量。

## 指令

- `[x]` `POST /api/devices/{id}/commands`：下发指令，落库 `command_log` 后发布；记录下发人 `issuedByName`。**发布到哪个 topic 由设备决定**：设备绑定了 `simulationId`（边端）→ `simulation/{simulationId}/command`，否则 → `robot/{deviceCode}/cmd`。
- `[x]` `GET /api/devices/{id}/commands?page=&size=`：下发记录与回执状态。
### 参数 / 策略 / 模型版本化与下发

版本行**不可变**：新建即新增一版，`version` 由服务端按 `max(version)+1` 自增；「下发」只改状态。「重发旧版本」就是回滚。

状态机：`DRAFT` --首次下发--> `PUBLISHED` --设备回执 SUCCESS--> `ACTIVE` --同范围出现更新的 ACTIVE--> `SUPERSEDED`。
**失败回执不改状态**（停在 `PUBLISHED`，可直接重发），所以失败的版本不会被误标成生效。

| 接口 | 说明 |
|---|---|
| `GET /api/devices/{id}/parameters?limit=50` | 该设备的参数版本列表 |
| `POST /api/devices/{id}/parameters` | 新建参数版本，体 `{ "payload": { ... } }` |
| `GET /api/devices/{id}/parameters/{version}` | 指定版本详情 |
| `POST /api/devices/{id}/parameters/{version}/publish` | 下发该版本到本设备 |
| `GET /api/devices/{id}/models?modelName=&limit=50` | 模型版本列表（可按名字过滤） |
| `POST /api/devices/{id}/models` | 新建模型版本，体 `{ "modelName": "...", "artifactUrl": "...", "metadata": { ... } }` |
| `GET /api/devices/{id}/models/{modelName}/{version}` | 指定模型版本详情 |
| `POST /api/devices/{id}/models/{modelName}/{version}/publish` | 下发该模型版本 |
| `GET /api/strategies?name=&limit=50` | 策略版本列表（策略是全局资源，不绑定设备） |
| `POST /api/strategies` | 新建策略版本，体 `{ "name": "...", "payload": { ... } }` |
| `GET /api/strategies/{name}/{version}` | 指定策略版本详情 |
| `POST /api/devices/{id}/strategies/{name}/{version}/publish` | 把某策略版本下发到某台设备 |
| `GET /api/devices/{id}/publishables` | 本设备可下发的全部版本（含当前 ACTIVE） |
| `GET /api/edge/publishables` | 同上，edge token 版 |

约束：`name` / `modelName` 只允许 `[A-Za-z0-9_.-]{1,64}`，参数与策略的 `payload` 必须是 JSON 对象，违反返回 `400`；指定版本不存在也返回 `400`。

下发复用指令通道（`cmdType` = `PARAMETER` / `STRATEGY` / `MODEL`），每次下发在 `command_log` 里都有一条记录，回执走 MQTT `cmd_ack` 或 `POST /api/edge/cmd-ack`：

```json
{ "kind": "PARAMETER", "version": 4, "messageId": "…", "status": "PUBLISHED", "commandResult": "PENDING", "rollback": false }
```

`kind` 取 `PARAMETER` / `STRATEGY` / `MODEL`；`rollback` 表示这次下发的是比当前 ACTIVE 更旧的版本。

### POST /api/devices/{id}/commands

请求体：

```json
{ "cmdType": "PARAMETER", "version": 1, "payload": { "kp": 1.2 } }
```

`cmdType` 必填；返回 `command_log` 记录，`result` 初始为 `PENDING`，收到 `cmd_ack` 后更新为 `SUCCESS` 或边缘端上报的结果；发布失败时直接置为 `FAILED` 并写入 `resultDetail`。回执可来自 MQTT（`robot/{deviceCode}/cmd_ack`）或 HTTP（`POST /api/edge/cmd-ack`）。

**边端设备（simulation 契约）用另一组字段**：

```json
{ "cmdType": "MOVE_JOINT", "jointTarget": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6], "speed": 0.5 }
```

- `cmdType` ∈ `START | STOP | MOVE_HOME | MOVE_JOINT`（设备未绑定 `simulationId` 时仍走上面那套 `PARAMETER/STRATEGY/MODEL/CONFIG`）。
- `MOVE_JOINT` 必须给 **6 个** `jointTarget`；`speed` 可选、取值 [0, 5]。校验失败返回 400 与中文原因。
- 返回体多两列：`simulationId`、`targetRobotId`（记下发时的 sim 与 robotId，设备改名/换绑后可追溯）。
- 边端执行后回执到 `simulation/{simId}/command_ack`（`commandId` = `message_id`），`command_log.result` 随即变 `SUCCESS/FAILED`，`resultDetail` 记边端反馈（如 `NN setpoint 已更新 target=[...]`）。

### GET /api/fault-events/statistics

```json
{
  "total": 3,
  "from": "1970-01-01T00:00:00",
  "to": "9999-01-01T00:00:00",
  "byLevel": [{ "key": "WARNING", "count": 3 }],
  "byType": [{ "key": "TORQUE_ABNORMAL", "count": 3 }],
  "byDay": [{ "key": "2026-09-19", "count": 3 }],
  "byDevice": [{ "deviceId": 1, "deviceCode": "robot-001", "deviceName": "仿真机械臂", "count": 3 }]
}
```

`from`/`to` 为实际生效区间：不传时用 `1970-01-01` / `9999-01-01` 覆盖全量；`deviceId` 省略即全量统计。

## 运行状态

- `[x]` `GET /api/health`：健康检查（免鉴权）。
- `[x]` `GET /api/system/stats`：遥测批量写入水位（`enqueued`/`inserted`/`dropped`/`failedFlushes`/`lastBatchSize`）、MQTT 坏报文计数（`malformedDropped`/`handlerFailed`）、设备总数/在线数、审计条数、uptime，以及遥测水位 `telemetry{detailRows, hourlyRows, lastArchivedAt}`。
- `[x]` `POST /api/system/archive?retentionDays=30&dryRun=true`（**仅 ADMIN**）：把保留期之前的遥测明细按「设备 + 小时」聚合成均值写入 `telemetry_hourly`，再按批（5000 行）删除明细。`dryRun` 默认 `true`，只统计候选不落盘——线上先 dryRun 看命中量，再 `dryRun=false` 真归档。返回 `{retentionDays, cutoff, dryRun, candidates, framesArchived, bucketsWritten, devicesTouched, finishedAt}`。

定时归档默认关闭（`TELEMETRY_ARCHIVE_ENABLED=false`），打开后每天 03:30（`TELEMETRY_ARCHIVE_CRON`）自动按 `app.telemetry.retention-days` 执行。