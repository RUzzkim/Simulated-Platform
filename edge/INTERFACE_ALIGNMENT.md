# 三端接口对齐清单（仿真端 / 边端 / 云端）

> 目的：在第一阶段联调前，统一三端接口契约，避免边端擅自改动已确定的云端接口。
> 状态：✅ 已对齐（无需改动） | ⚠️ 待决策（需三端确认后再编码）
> 版本：v0.1　日期：2026-09-18

---

## 一、✅ 已对齐项（基线，禁止改动）

以下项已在云端代码中实现，三端必须严格遵守，边端已按此实现。

### 1.1 MQTT 基础配置
| 项 | 值 | 云端依据 |
|---|---|---|
| Broker 地址 | `tcp://localhost:1883` | `application.yml` mqtt.broker-url |
| QoS | `1` | `MqttConfig.java` setQos(1) |
| Client ID | 云端 `platform-backend`，边端自定 | `application.yml` mqtt.client-id |

### 1.2 MQTT Topic（必须精确匹配）
| 方向 | Topic | 云端依据 |
|---|---|---|
| 边端→云（状态） | `simulation/{simulationId}/state` | `state-topic-pattern: simulation/+/state` |
| 边端→云（心跳） | `simulation/{simulationId}/heartbeat` | `heartbeat-topic-pattern: simulation/+/heartbeat` |
| 云→边端（指令） | `simulation/{simulationId}/command` | `CommandService.java` 发布到此 |
| 云→边端（配置） | `simulation/{simulationId}/config` | `MqttConfig.java` 默认 outbound topic |

### 1.3 ID 与时间戳格式
| 项 | 规则 | 云端依据 |
|---|---|---|
| simulationId | `^SIM-\d{3}$`（如 SIM-001） | `RobotState.java` / `Heartbeat.java` @Pattern |
| robotId | `^ROBOT-\d{3}$`（如 ROBOT-001） | 同上 |
| timestamp | Unix 毫秒级时间戳（int64） | `@Min(1000000000000) @Max(9999999999999)` |

### 1.4 RobotState（state topic 载荷）
字段名、类型、长度、单位、枚举禁止修改：
```json
{
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "timestamp": 1760000000123,
  "jointPosition": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
  "jointVelocity": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
  "jointTorque": [1, 2, 3, 4, 5, 6],
  "status": "RUNNING"
}
```
- `jointPosition` / `jointVelocity` / `jointTorque`：长度必须为 6
- 单位：rad / rad/s / N·m
- `status` 枚举：`RUNNING` | `STOPPED` | `ERROR`
- 云端校验见 `MqttMessageHandler.validateRobotState()`

### 1.5 Heartbeat（heartbeat topic 载荷）
```json
{
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "timestamp": 1760000000123,
  "status": "ONLINE"
}
```
- `status` 枚举：`ONLINE` | `OFFLINE`

### 1.6 RobotCommand（command topic 载荷，云端→边端）
云端 `CommandService.java` 实际发布的 JSON 结构：
```json
{
  "commandId": "CMD-XXXXXXXX",
  "simulationId": "SIM-001",
  "robotId": "ROBOT-001",
  "cmdType": "MOVE_JOINT",
  "jointTarget": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
  "speed": 1.0,
  "timestamp": 1760000000123
}
```
- `jointTarget`：长度 6，单位 rad，`MOVE_JOINT` 时必填
- `speed`：范围 [0, 5]

---

## 二、⚠️ 待决策项（需三端确认）

### 2.1 【指令枚举冲突】`cmdType` 中 `STOP` 还是 `STOPPED`？

**现状：**
- 云端 `openapi.yaml` 定义枚举为：`START, STOP, MOVE_HOME, MOVE_JOINT`
- 云端 `RobotCommand.java` 校验正则为：`START|STOPPED|MOVE_HOME|MOVE_JOINT`（含 `STOPPED`，不含 `STOP`）
- 边端 `model/messages.py` 当前按 `openapi.yaml` 实现为 `STOP`

**影响：** 前端发 `STOP` 会通过 openapi 校验但被 DTO 正则拒绝；发 `STOPPED` 则相反。三端必须统一。

**推荐方案：** 统一为 `STOP`（更符合动词指令语义），云端修改 `RobotCommand.java` 正则为 `START|STOP|MOVE_HOME|MOVE_JOINT`。

**决策：** 云端负责人确认 → 以 `____` 为准（STOP / STOPPED）

---

### 2.2 【ROS 2 状态消息】`joint_states` 用标准消息还是自定义消息？

**现状：**
- 边端暂定订阅 `/simulation/{simulationId}/joint_states`，消息类型 `sensor_msgs/JointState`
- 标准 `JointState` 字段：`header.stamp`、`name[]`、`position[]`、`velocity[]`、`effort[]`
- 云端需要的 `simulationId` / `robotId` / `status` 在 `JointState` 中**不存在**

**边端当前处理（phase1）：**
- `simulationId`：从 ROS 2 Topic 名 `/simulation/SIM_001/joint_states` 解析，并将 ROS 2 安全段 `SIM_001` 映射回设备标识 `SIM-001`
- `robotId`：边端本地配置注入
- `timestamp`：`header.stamp` 纳秒→毫秒
- `status`：默认 `RUNNING`（无来源）

**问题：**
1. `robotId` 若一仿真多机械臂，如何区分？
2. `status`（RUNNING/STOPPED/ERROR）由谁产生、如何传到边端？

**可选方案：**
- A. 保持 `sensor_msgs/JointState`，`robotId` 放 `name[]` 首元素或单独 topic，`status` 由边端根据指令推断
- B. 自定义 ROS 2 消息 `RobotStateMsg`，含 `simulationId/robotId/timestamp/jointPosition/jointVelocity/jointTorque/status`

**推荐方案：** 方案 A（phase1 先用标准消息快速跑通，`status` 暂固定 RUNNING；仿真端开发时再决定是否切自定义消息）。

**决策：** 仿真端负责人确认 → 方案 `____`（A / B）

---

### 2.3 【ROS 2 控制指令】`joint_command` 消息类型与字段？

**现状：**
- 边端暂定发布 `/simulation/{simulationId}/joint_command`，消息类型 `std_msgs/Float64MultiArray`（仅目标关节位置）
- 云端 `command` topic 下发的 `cmdType` 有 4 种：`START / STOP / MOVE_HOME / MOVE_JOINT`
- `MOVE_JOINT` 有 `jointTarget[6]`；`START/STOP/MOVE_HOME` 无目标位置

**问题：**
1. 仿真端 `joint_command` 期望什么消息类型？
2. `START/STOP/MOVE_HOME` 如何映射为 ROS 2 指令？（当前边端仅 `MOVE_JOINT` 和 `MOVE_HOME` 转位置，`START/STOP` 仅日志）

**可选方案：**
- A. `std_msgs/Float64MultiArray`（6 个目标角度），`START/STOP` 走独立 topic 或约定特殊值
- B. 自定义消息含 `commandType / targetPosition / targetVelocity / targetTorque`

**推荐方案：** phase1 用方案 A，`MOVE_HOME` → 全 0，`MOVE_JOINT` → jointTarget，`START/STOP` 暂不映射位置（后续扩展）。

**决策：** 仿真端负责人确认 → 消息类型 `____`

---

### 2.4 【状态 status 来源】`RobotState.status` 如何确定？

**现状：** 标准 `JointState` 无 `status` 字段，边端 phase1 默认 `RUNNING`。

**问题：** 机械臂 `STOPPED` / `ERROR` 状态由谁判定？
- 仿真端直接上报？
- 边端根据关节速度/力矩推断？
- 云端根据指令状态推断？

**推荐方案：** phase1 由边端根据是否收到 `STOP` 指令置 `STOPPED`，力矩超限置 `ERROR`；后续由仿真端在自定义消息中直接携带。

**决策：** 三端确认 → `____`

---

### 2.5 【config 消息结构】云端 `config` topic 的 JSON 字段？

**现状：**
- 云端 `MqttConfig.java` 预留了 `simulation/{simulationId}/config` 作为 outbound topic，但**尚无 Service 发布**
- 边端已实现订阅与 `EdgeConfig` 解析（预留字段：`controlMode / controlRate / algorithmParams / simParams`）

**问题：** 云端何时实现 config 下发？具体 JSON 结构？

**推荐方案：** phase1 云端暂不发布 config，边端使用本地 `edge_config.yaml`；phase2 由云端定义结构后三端对齐。

**决策：** 云端负责人确认 → config 结构 `____`

---

### 2.6 【频率参数】心跳周期与状态上传频率？

**现状：**
- 边端默认心跳 5s/次，状态上传 10Hz（降频后上传）
- 云端未声明心跳超时阈值

**问题：**
1. 云端判定边端离线的心跳超时时间？（需 > 心跳周期）
2. 机械臂关节数据可能 100Hz+，MQTT 上传是否需要降频？降到多少？

**推荐方案：** 心跳 5s，云端超时 15s（3 次）；状态上传 10Hz。

**决策：** 云端 + 边端确认 → 心跳 `____`s，状态上传 `____`Hz，云端超时 `____`s

---

### 2.7 【未实现 Topic】`fault` / `result` topic 是否纳入第一阶段？

**现状：**
- 用户原始设计提到 `simulation/{simulationId}/fault` 和 `simulation/{simulationId}/result`
- 云端 `MqttMessageHandler` 仅订阅 `state` 和 `heartbeat`，**未实现** `fault` / `result`
- 边端故障检测模块为 stub，暂不发布

**推荐方案：** phase1 不纳入 `fault` / `result`，待故障检测模块开发时再与云端对齐。

**决策：** 三端确认 → phase1 是否包含 `____`

---

## 三、确认签字

| 端 | 负责人 | 日期 | 确认 |
|---|---|---|---|
| 云端 | | | ☐ |
| 边端 | | | ☐ |
| 仿真端 | | | ☐ |

---

## 四、变更规则

1. 已对齐项（第一节）禁止任何一方单方面修改，需走本清单变更流程。
2. 待决策项（第二节）未确认前，边端按「推荐方案」实现并打 TODO 标记，确认后统一调整。
3. 任何接口变更必须同步更新：`openapi.yaml`、`schemas.json`、云端 DTO、边端 `model/messages.py`。
