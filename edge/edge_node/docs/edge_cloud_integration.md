# 端 - 边 - 云 联调接口文档（边端侧）

| 项 | 值 |
|---|---|
| 版本 | v1.1（对应边端代码 2026-09-19 状态，RobotState 新增可选 `faults`） |
| 适用节点 | `backend/edge_node`（Python 3.10+，无强制 ROS 2 依赖） |
| 通信中间件 | MQTT v3.1.1（paho-mqtt），QoS 统一 1（至少一次） |
| 数据编码 | UTF-8 JSON，字段名 **camelCase**，时间戳统一**毫秒级 Unix** |
| 身份模型 | 一个边端节点 = 一个 `simulationId` + 一个 `robotId`（1:1 边端实例，云端侧 1:N 绑定由云端维护） |

> 字段名、枚举、数组长度为三方契约（见 `docs/contract/openapi.yaml`），**禁止单边修改**；扩展只能新增可选字段并经三方确认。

---

## 1. 总体架构与数据流

```
        仿真端（机械臂仿真平台）                         云端（Spring Boot）
  ┌───────────────────────────────┐            ┌──────────────────────┐
  │ ROS 2: /simulation/<id>/      │            │  REST 8080（前端/管理）│
  │        joint_states           │            │  MQTT 入站:            │
  │ MQTT: simulation/<id>/        │            │   .../state            │
  │        sim_state  (100Hz)     │            │   .../heartbeat        │
  └──────────────┬────────────────┘            │  MQTT 出站:            │
                 │                             │   .../command          │
                 │ ① 原始状态接入（二选一）      │   .../config（预留）   │
                 ▼                             └──────────┬───────────┘
        ┌────────────────────────────┐                    │
        │          边端节点            │◄───────────────────┤
        │ ②信号滤波→③状态推断         │  ④指令/配置下发      │
        │   →故障检测→容错控制         ├──────────────────► 状态/心跳上报
        │                            │   (10Hz / 5s)       │
        │ 容错期：MOVE_JOINT_SAFE ────┼────────────────────┼──► 仿真端
        │         （复用 command）    │  ⑥安全指令（边-端内部）
        └────────────────────────────┘
```

三段链路：

1. **端 → 边（接入）**：有 ROS 2 环境走 DDS topic；无 ROS 2（联调/部署默认）走 MQTT `sim_state`。两种输入进入**同一个处理入口**，行为完全一致。
2. **边 → 云（上报）**：处理后的状态降频 10Hz 发 `state`；心跳 5s 发 `heartbeat`。
3. **云 → 边（下行）/ 边 → 端（执行器闭环）**：云端指令经 `command` 下发；边端在无 ROS 2 模式下把容错安全目标复用 `command` 主题发回仿真端（内部前缀区分，云端可见状态推断不受影响）。

---

## 2. 端 → 边：数据接入方式

边端启动时自动探测 `rclpy` 是否可导入（[main.py](../edge_node/main.py#L178-L186)）：

| 模式 | 判定 | 接入通道 | 指令回注通道 |
|---|---|---|---|
| ROS 2 模式 | `import rclpy` 成功 | 订阅 `/simulation/{simulationId}/joint_states`（`sensor_msgs/JointState`，取 position/velocity/effort 三个 6 维数组与 header.stamp 纳秒戳） | 发布 `/simulation/{simulationId}/joint_command`（`std_msgs/Float64MultiArray`，6 目标角度 rad） |
| 无 ROS 2 模式（联调默认） | `rclpy` 不可用 | MQTT 订阅 `simulation/{simulationId}/sim_state`，载荷即 `RobotState` JSON（见 §5.1），默认 100Hz | MQTT 向 `simulation/{simulationId}/command` 发 `MOVE_JOINT_SAFE`（见 §5.5） |

接入约定：

- 数组长度恒为 **6**（6 轴，索引 0=基座 … 5=腕部）；单位 rad / rad·s⁻¹ / N·m。
- `sim_state` 载荷中 `timestamp` 为仿真端采集时刻毫秒戳，边端原样透传上报（端-边-云时间戳同源，便于延迟分析）。
- 无 ROS 2 模式下边端**不向 sim_state 发任何数据**，且上报主题是独立的 `.../state`，物理上避免自环。

仿真端发送示例（联调模拟器 [simulation_simulator.py](../test/simulation_simulator.py)，100Hz）：

```json
{
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "timestamp": 1789802266532,
  "jointPosition": [0.001, 0.0, 0.0, 0.0, 0.0, 0.0],
  "jointVelocity": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
  "jointTorque": [0.12, 6.03, 4.01, 1.21, 0.40, 0.39],
  "status": "RUNNING",
  "faults": []
}
```

> 仿真端自身不做故障检测，其 `faults` 恒为 `[]`；该字段存在仅为保持与 RobotState 同构。

---

## 3. 边端数据处理流程

所有输入（ROS 2 / MQTT）汇入唯一入口 `handle_joint_state(position, velocity, effort, stamp_ns)`（[main.py](../edge_node/main.py#L136-L166)），五级流水线：

```
原始 6×3 观测
  │
  ├─① RobotSignalFilter  信号滤波与离群点剔除（processor/signal_filter.py）
  │    MAD 稳健离群判定(k=3.5，min_sigma 静止兜底) → 奇数窗中值(窗3) → EMA(α 0.8/0.5/0.5)
  │    离群帧：输出端 hold 上一有效值；原始观测照常入统计窗（保证持续物理变化 ≤3 帧穿透）
  │
  ├─② StateProcessor     状态推断（processor/state_processor.py）
  │    任一 |τ| > max_torque(50) → ERROR；否则取指令状态(STOP→STOPPED，其余→RUNNING)；否则默认 RUNNING
  │
  ├─③ CompositeFaultDetector 故障检测（fault/detector.py）
  │    NaN/越限/超速（即时） + 持续过载/卡死（20 帧窗 + persistence=5）
  │    CRITICAL 故障强制 state.status='ERROR'
  │
  ├─④ FaultTolerantController 容错（故障期才动作）
  │    过载误差缩放 0.3、速度异常单步钳位 0.05rad、恢复帧 10、DLS 主动重规划
  │
  └─⑤ latest_state（加锁共享） → 上报线程 10Hz 发布；故障期安全指令线程 10Hz 下发仿真端
```

线程模型（均为 daemon 线程，状态回调单线程，模块非线程安全靠一把 `state_lock` 保护共享态）：

| 线程 | 周期 | 职责 |
|---|---|---|
| paho 网络线程 | 事件驱动 | 接收 sim_state / command / config，触发回调 |
| 状态发布线程 | 10Hz（`state_publish_hz`） | 顺带做通信超时检测（>500ms 无观测 → WARNING），发布最新 state |
| 心跳线程 | 5s（`heartbeat_interval_sec`） | 发布 ONLINE 心跳 |
| 安全指令线程（仅无 ROS 2 且启用容错） | 10Hz | 故障期发 EDGE-SAFE，恢复瞬间发一次 EDGE-RESUME |
| NN 闭环线程（仅 adaptive_nn + ROS 2） | 100Hz | RBF 自适应控制输出 joint_command |

---

## 4. 边端 MQTT Client

实现：[mqtt_client.py](../edge_node/mqtt_client.py)（paho-mqtt 封装）。

| 特性 | 实现 |
|---|---|
| 协议/鉴权 | MQTT v3.1.1；可选 username/password（`username_pw_set`） |
| Broker | `tcp://host:port`，默认 `tcp://localhost:1883` |
| client_id | `edge-node-<simulationId>`（同仿真多实例必须改，避免互踢） |
| QoS | 全部 1（至少一次）；下游需自行按 commandId 幂等 |
| keepalive | 60s |
| 自动重连 | `reconnect_delay_set(1, 30)`：断线后 1→30s 退避重连，重连成功自动重新订阅全部 topic |
| 遗嘱 LWT | 连接时在 heartbeat 主题预置 `{"status":"OFFLINE",...}`；进程异常退出 broker 代发 OFFLINE |
| 优雅下线 | `disconnect()` 先发一帧 OFFLINE 心跳再断开 |
| 发布串行化 | 所有 publish 过同一把锁；payload `ensure_ascii=False` |
| 坏消息处理 | UTF-8/JSON 解析失败仅记 error 日志，不断连、不抛穿网络线程 |

订阅在 `on_connect` rc=0 时完成（重连后会重复执行，保证订阅恢复）：`command`、`config`，无 ROS 2 模式再加 `sim_state`。

---

## 5. MQTT Topic 与 JSON 消息定义

### 5.0 Topic 总览（`{id}` = simulationId，如 SIM-001）

| # | 方向 | Topic | QoS | 频率 | 载荷 |
|---|---|---|---|---|---|
| 1 | 端 → 边 | `simulation/{id}/sim_state` | 1 | 100Hz | RobotState（§5.1） |
| 2 | 边 → 云 | `simulation/{id}/state` | 1 | **10Hz** | RobotState（§5.1） |
| 3 | 边 → 云 | `simulation/{id}/heartbeat` | 1 | **5s** | Heartbeat（§5.2） |
| 4 | 云 → 边 | `simulation/{id}/command` | 1 | 事件触发 | RobotCommand（§5.3） |
| 5 | 云 → 边 | `simulation/{id}/config` | 1 | 事件触发 | EdgeConfig（§5.4，预留） |
| 6 | 边 → 端（内部） | `simulation/{id}/command`（复用#4） | 1 | 故障期 10Hz / 恢复 1 帧 | MOVE_JOINT_SAFE（§5.5） |

> Topic 全部可在 [edge_config.yaml](../config/edge_config.yaml#L16-L29) 配置，支持 `{simulation_id}` 占位符渲染。#1/#2 必须保持不同主题，否则边端会收到自己上报的消息形成回环。

### 5.1 RobotState（端→边 sim_state 与 边→云 state 同构）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| simulationId | string | `^SIM-\d{3}$` | 必填 |
| robotId | string | `^ROBOT-\d{3}$` | 必填 |
| timestamp | int | 毫秒级 13 位 Unix | sim_state 中为采集时刻；边端上报时透传 |
| jointPosition | number[6] | rad，元素必须数值 | 关节角 |
| jointVelocity | number[6] | rad/s | 关节速度 |
| jointTorque | number[6] | N·m | 关节力矩（含真实负载与故障力矩） |
| **status** | string enum | `RUNNING` / `STOPPED` / `ERROR` | **异常状态字段**，见 §7 |
| faults | object[] | v1.1 起恒在；无故障为 `[]` | **本帧检测到的故障明细**（0 或 1 条，检测器按优先级每帧至多返回一条），结构见下 |

`faults[]` 元素结构（与边端 FaultEvent 一一对应，全部 camelCase）：

| 字段 | 类型 | 取值 |
|---|---|---|
| faultType | string enum | `TORQUE_OVERLOAD` / `JOINT_LOCKED` / `VELOCITY_ANOMALY` / `SENSOR_INVALID` / `COMMUNICATION_TIMEOUT` |
| jointIndex | int | 故障关节索引 0-5；通信超时为 **-1** |
| severity | string enum | `WARNING` / `ERROR` / `CRITICAL` |
| timestamp | int | 毫秒，与所在 state 帧同源 |
| detail | string | 英文判据描述（含实测值与阈值），供日志/排障，勿做程序化分支 |

示例（过载帧）：

```json
"faults": [{
  "faultType": "TORQUE_OVERLOAD",
  "jointIndex": 0,
  "severity": "ERROR",
  "timestamp": 1789804955352,
  "detail": "joint 0 sustained avg torque 60.0 > 40.0"
}]
```

**兼容性**：`faults` 是纯加法字段，既有字段/枚举/Topic/频率均不变；旧版云端用 Spring Boot 默认 ObjectMapper（`FAIL_ON_UNKNOWN_PROPERTIES=false`）会静默忽略该字段，已在真实云端验证（消息正常入库、REST/心跳不受影响）。边端可经 `runtime.publish_faults` / `EDGE_PUBLISH_FAULTS=false` 关闭明细（关闭后帧内恒为 `[]`，键仍保留）。

边端侧构造时强校验（[messages.py](../edge_node/model/messages.py#L75-L132)）：不合规直接抛 `ValueError`，不会发出脏消息。

### 5.2 Heartbeat（边 → 云）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| simulationId | string | `^SIM-\d{3}$` | |
| robotId | string | `^ROBOT-\d{3}$` | 正常心跳为边端 robotId；**LWT/下线帧为空串 `""`**（仅表达仿真级离线） |
| timestamp | int | 毫秒 | 下线帧为 `0` |
| **status** | string enum | `ONLINE` / `OFFLINE` | 在线 5s 一帧；异常退出由 broker 遗嘱代发 OFFLINE，主动退出边端先发 OFFLINE |

### 5.3 RobotCommand（云 → 边）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| commandId | string | 非空 | 幂等键，下游按它去重 |
| simulationId | string | `^SIM-\d{3}$` | |
| robotId | string | `^ROBOT-\d{3}$` | |
| cmdType | string enum | `START` / `STOP` / `MOVE_HOME` / `MOVE_JOINT` | STOP 后边端清空活动目标并上报 STOPPED |
| timestamp | int | 毫秒 | |
| jointTarget | number[6]? | MOVE_JOINT 时必填且长度 6（rad） | 其余指令省略 |
| speed | number? | [0, 5] rad/s | 可选 |

示例：

```json
{
  "commandId": "CMD-4BF153C8",
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "cmdType": "MOVE_JOINT",
  "jointTarget": [0.8, 0, 0, 0, 0, 0],
  "speed": 0.25,
  "timestamp": 1789802200000
}
```

### 5.4 EdgeConfig（云 → 边，预留）

边端宽容解析、未知字段保留在 `raw`：`controlMode`（string）、`controlRate`（number）、`algorithmParams`（object）、`simParams`（object）。收到后热更新运行参数（[main.py](../edge_node/main.py#L241-L243)）。云端正式定义前该主题可空置。

### 5.5 MOVE_JOINT_SAFE（边 → 端，边-端内部协议）

复用 command 主题，以 cmdType 与 commandId 前缀区分，**云端不应将其作为用户指令计入状态推断**：

```json
// 故障持续期：10Hz，仿真端清除梯形规划、按 safe-vmax(默认0.1rad/s) 限速逼近
{
  "commandId": "EDGE-SAFE-1789802210123",
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "cmdType": "MOVE_JOINT_SAFE",
  "jointTarget": [0.24, 0, 0, 0, 0, 0],
  "timestamp": 1789802210123
}

// 恢复瞬间：仅一帧，仿真端退出安全模式并对云端原目标重新梯形规划
{ "commandId": "EDGE-RESUME-1789802214567", "simulationId": "SIM-001",
  "robotId": "ROBOT-001", "cmdType": "MOVE_JOINT_SAFE", "resume": true,
  "timestamp": 1789802214567 }
```

仅在「无 ROS 2 模式 + `safe_command_enabled=true` + 容错启用」时存在；ROS 2 模式下等价动作走 joint_command。

---

## 6. 消息频率与时序预算

| 链路 | 名义频率 | 备注 |
|---|---|---|
| 端 → 边 sim_state / ROS joint_states | 100Hz（周期 10ms） | 联调模拟器 `--rate 100` |
| 滤波引入延迟 | ≤ 30ms | 窗 3 中值（≤20ms）+ EMA 群延迟（α=0.8 位置约 2.5ms） |
| 持续故障穿透 | ≤ 3 帧（≤30ms） | 离群剔除不锁基线，真实过载阶跃不被滤掉 |
| 边 → 云 state | 10Hz（100ms） | 高频观测降频上报；取最新一帧 |
| 边 → 云 heartbeat | 0.2Hz（5s） | |
| 故障确认延迟 | 过载/卡死：窗 20 帧 + 持续 5 帧 ≈ 250ms@100Hz；NaN/超速/单帧超限：当帧 | |
| 通信超时判定 | 500ms 无观测 → COMMUNICATION_TIMEOUT(WARNING) | 在状态发布线程检查 |
| MQTT keepalive / 重连 | 60s / 1~30s 退避 | |

---

## 7. 异常状态字段与故障语义

### 7.1 上云的异常表达（契约内）

| 信号 | 字段 | 取值 | 触发 |
|---|---|---|---|
| 机械臂运行异常 | `RobotState.status` | `ERROR` | ① 任一关节单帧 \|τ\| > 50 N·m（状态推断层）；② 检测器输出 CRITICAL 故障（传感器 NaN、关节卡死） |
| 正常停止 | 同上 | `STOPPED` | 收到 STOP 指令且无力矩超限 |
| 正常运行 | 同上 | `RUNNING` | 其余情况 |
| 边端在线状态 | `Heartbeat.status` | `ONLINE` / `OFFLINE` | 5s 心跳；异常退出 LWT、主动下线、重连失败期间无 ONLINE |

云端判活建议：heartbeat 超时阈值 ≥ 15s（3 个心跳周期）；state 中断 >500ms 边端即检出 COMMUNICATION_TIMEOUT（WARNING）——不改变 status，但 v1.1 起会在停摆期重发帧的 `faults` 中明示（jointIndex=-1）。

### 7.2 故障明细（FaultEvent，v1.1 起随 state.faults 上云）

| faultType | severity | 判定规则（默认参数） | 上云时机 |
|---|---|---|---|
| SENSOR_INVALID | **CRITICAL** | 任一通道 NaN（当帧） | 检出即随帧 |
| SENSOR_INVALID | ERROR | 任一 \|q\| > 6.28 rad（当帧） | 检出即随帧 |
| VELOCITY_ANOMALY | ERROR | 任一 \|q̇\| > 3.0 rad/s（当帧） | 检出即随帧 |
| TORQUE_OVERLOAD | ERROR | 窗口(20帧)平均 \|τ\| > 40 N·m 且持续 5 帧 | 确认后持续随帧，恢复即清空 |
| JOINT_LOCKED | **CRITICAL** | 窗口位置极差 < 0.001rad 且平均 \|τ\| > 10 N·m，持续 5 帧 | 同上 |
| COMMUNICATION_TIMEOUT | WARNING | >500ms 无状态输入 | 停摆期间挂在重发帧上（jointIndex=-1），**不改变 status** |

语义说明：

- `faults` 表示**该帧检出时刻的活动故障**，不是事件流/历史列表；故障消失后下一帧即为 `[]`，云端无需自行去抖，但需按帧覆盖而非累加。
- 检测器按上表优先级每帧至多返回一条故障，故数组长度当前只可能是 0 或 1；云端解析应按数组（而非单对象）实现，为未来同帧多故障留余地。
- 三态 `status` 与 faults 并行不悖：WARNING 不上抬 status；ERROR/CRITICAL 故障通常伴随 `status=ERROR`（卡死/NaN 为强制，过载由状态推断层的 50 N·m 单帧阈值联动）。
- 云端当前版本不识别该字段时静默忽略（已实测）；云端正式消费后可用于告警列表/故障定位，无需边端再改协议。

---

## 8. 联调步骤（无 ROS 2 全 MQTT 模式）

前置：Python 3.10+，`pip install paho-mqtt pyyaml`（见 requirements.txt）。

```powershell
# 终端 1：MQTT broker（自研极简 broker，1883）
py -B test\start_mqtt_broker.py

# 终端 2：边端节点（cwd = backend/edge_node）
py -B -m edge_node.main --config config\edge_config.yaml
# 期望日志：MQTT 已连接 / 信号滤波已启用 / 故障检测已启用 / 容错控制已启用

# 终端 3：仿真端模拟器（100Hz，可选注入过载与噪声）
py -B test\simulation_simulator.py --sim-id SIM-001 --robot-id ROBOT-001 `
  --mode hold --duration 20 --rate 100 `
  --fault overload --fault-delay 2.5 --fault-duration 3.0
```

订阅抓包锚点（可用任一 MQTT 客户端，如 mosquitto_sub）：

- `simulation/SIM-001/sim_state`：100Hz 原始观测（端→边）
- `simulation/SIM-001/state`：10Hz 滤波/处理后观测（边→云），故障窗口内应出现 `status=ERROR`
- `simulation/SIM-001/heartbeat`：5s ONLINE
- `simulation/SIM-001/command`：云端指令 + 故障期 `EDGE-SAFE-*`（10Hz）与恢复帧 `EDGE-RESUME-*`

联调判定内容锚点（不要只按墙钟等待）：state 中出现 `|jointTorque[i]| > 40` 后 250ms 内应能观察到容错行为（command 上出现 EDGE-SAFE）；力矩恢复后 10 帧内出现一次 EDGE-RESUME。

云端在场时（Spring Boot，8080 + 同 broker）：先用 REST 完成实例与绑定（`POST /api/simulations` 携带 robotIds，或 `PUT /api/simulations/SIM-001/robots`），其 MQTT 入站消费 #2/#3、经 #4 下发指令。

### 常见问题

| 现象 | 排查 |
|---|---|
| 边端日志"MQTT 异常断开 rc=…" | broker 未启动/端口占用；客户端会自动 1~30s 重连，无需重启 |
| 云端显示 OFFLINE / 无状态 | 确认云端订阅主题与 §5.0 完全一致；确认 simulationId/robotId 已在云端绑定 |
| 仿真端不动 | 无 ROS 2 模式必须经 command 收到 MOVE_JOINT（云端）或 EDGE-SAFE（容错）；hold 模式默认保持零位 |
| 收到自己发的 state 形成回环 | sim_state 与 state 主题被改成同名；恢复默认配置 |
| 坏 JSON | 边端只记 error 日志不断连；修复发送方即可，无需重启边端 |

---

## 9. 配置与环境变量

配置文件：[config/edge_config.yaml](../config/edge_config.yaml)；环境变量（启动时覆盖 yaml，均可选）：

| 环境变量 | 覆盖项 |
|---|---|
| `EDGE_SIMULATION_ID` | edge.simulation_id |
| `EDGE_ROBOT_ID` | edge.robot_id |
| `EDGE_HEARTBEAT_INTERVAL` | runtime.heartbeat_interval_sec |
| `EDGE_STATE_PUBLISH_HZ` | runtime.state_publish_hz |
| `EDGE_SAFE_COMMAND_ENABLED` | control.safe_command_enabled |
| `EDGE_SIGNAL_FILTER_ENABLED` | signal_filter.enabled |
| `EDGE_PUBLISH_FAULTS` | runtime.publish_faults |

关键默认值：上报 10Hz、心跳 5s、滤波启用（窗 3 / k 3.5 / α 0.8·0.5·0.5）、检测启用（窗 20 / persistence 5 / τ 阈值 40 / 超速 3.0 / 超时 500ms）、容错启用（缩放 0.3 / 钳位 0.05 / 恢复 10 帧 / 主动重规划开）。

部署：仓库提供 `Dockerfile` / `docker-compose.yml` / `docker-entrypoint.sh`；ROS 2 环境可用 `launch/edge.launch.py`。

---

## 10. 修订记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.1 | 2026-09-19 | RobotState 新增可选 `faults` 故障明细数组（§5.1/§7.2）：故障帧携带 faultType/jointIndex/severity/timestamp/detail，无故障为 `[]`；新增开关 `runtime.publish_faults` / `EDGE_PUBLISH_FAULTS`（默认开）。纯加法变更，旧云端忽略已实测；过载真实链路 9/9 断言通过（含停摆 COMMUNICATION_TIMEOUT 通道），模型单测 15/15 |
| v1.0 | 2026-09-19 | 首版：双通道接入、五级处理流、MQTT Client、6 个 Topic、RobotState/Heartbeat/RobotCommand/EdgeConfig/MOVE_JOINT_SAFE 消息定义、频率预算、异常字段与故障语义、无 ROS 2 联调步骤。与 99/99 回归（单测 13 + 过载回归 12 + 噪声对照 17 + 云端绑定契约 18 等）后的边端代码一致 |
