# V2.0 单关节卡滞实验契约（冻结版）

- 契约版本：`2.0.0`
- 冻结日期：2026-11-26
- 责任：成员 C（边缘/云集成）
- 对齐基线：成员 B 的 validation-r1 冻结判据、场景与种子；远程提交 `a0a6b3b`
- 状态：冻结。新增字段走版本升级流程，见第 8 节。

本契约定义 V2.0 实验记录的**规范化字段**，用于云端索引、查询、导出和回放。它不替换既有 MQTT `RobotState`/`Heartbeat` 契约（见 `edge/edge_node/docs/contract/schemas.json`）；MQTT 字段仍是毫秒时间戳、6 维关节数组和 `SIM-###`/`ROBOT-###` 格式。

## 1. 记录结构

一次运行由两条记录组成，均以 `run_id` 为主键：

| 记录 | 粒度 | 文件 | Schema |
|---|---|---|---|
| Run | 每次运行 1 条 | `summary.runs[]` 规范化后 | [`v2_run.schema.json`](../edge/edge_node/docs/contract/v2_run.schema.json) |
| TraceFrame | 每个控制周期 1 条，800 帧/次 | `<run_id>.csv.gz` 规范化后 | [`v2_trace_frame.schema.json`](../edge/edge_node/docs/contract/v2_trace_frame.schema.json) |

原始 CSV 继续按 B 的格式保存，不重新写入；规范化在入库/导出时完成。字段来源分三类：

- **raw**：原始 summary/CSV 直接提供。
- **derived**：由原始字段确定性计算（如末端位姿、绝对检测时刻、任务状态）。
- **envelope**：契约新增的追溯字段（版本、运行开始时间、源码哈希）。

## 2. Run 记录字段

| 字段 | 类型 | 单位/取值 | 必填 | 来源 | 说明 |
|---|---|---|---|---|---|
| `contract_version` | string | 固定 `2.0.0` | 是 | envelope | 契约版本 |
| `run_id` | string | 32 位小写十六进制 | 是 | raw | 唯一运行 ID，等于轨迹文件名去扩展名 |
| `algorithm_version` | string | `vX.Y.Z` | 是 | envelope | off=`v0.0.0`，v1=`v1.0.0`，v2=`v2.0.0` |
| `started_at_ms` | integer | Unix 毫秒 | 是 | envelope | 批次时间基准，用于 `sim_time→epoch` 映射；见 6.2 |
| `simulation.simulation_id` | string | `^SIM-\d{3}$` | 是 | envelope | 固定 `SIM-001` |
| `simulation.robot_id` | string | `^ROBOT-\d{3}$` | 是 | envelope | 固定 `ROBOT-001` |
| `simulation.plant` | string | `python-6r` / `ros2-gazebo` | 是 | envelope | 本轮为 `python-6r` |
| `simulation.control_hz` | integer | 固定 `100` | 是 | raw | 与 `DT=0.01` 一致 |
| `simulation.duration_s` | number | 固定 `8.0` | 是 | raw | 单次仿真时长 |
| `scenario.scenario_id` | string | 场景名 | 是 | raw | 如 `VALIDATION-LOCK-J0#s1T1` |
| `scenario.split` | string | `development`/`exploratory`/`validation` | 是 | raw | 本契约冻结 validation-r1 |
| `scenario.seed` | integer | 0–2³¹−1 | 是 | raw | validation 为 300/301/302，见第 5 节 |
| `scenario.task_goal_rad` | number[6] | rad | 是 | raw | 原任务关节目标 |
| `scenario.description` | string | — | 是 | raw | 场景说明 |
| `fault.type` | string | 固定 `JOINT_LOCKED` | 是 | raw | 本轮只冻结单关节卡滞 |
| `fault.joint_index` | integer | 0–5 | 是 | raw | 与 `fault_joint` 一致 |
| `fault.joint_name` | string | `^J[0-5]$` | 是 | derived | 由索引生成，J0 为基座回转 |
| `fault.injected_at_s` | number | s（仿真时间） | 是 | raw | 等于 `fault_onset_s` |
| `fault.detected_at_s` | number/null | s（仿真时间） | 是 | derived | 注入时刻 + 确认延迟；未检出为 null |
| `fault.detection_latency_ms` | number/null | ms | 是 | raw | `fault_detection_latency_ms` |
| `fault.confirmed` | boolean | — | 是 | derived | `detection_latency_ms != null` |
| `reachability.status` | string | `REACHABLE`/`NO_FEASIBLE_PLAN`/`NOT_ASSESSED` | 是 | derived | 见 2.1 |
| `reachability.reason` | string/null | 决策原因 | 是 | derived | 如 `TARGET_REACHED`、`NO_FEASIBLE_PLAN` |
| `reachability.planner_position_error_m` | number/null | m | 否 | raw | 规划器位置误差；当前 summary 未导出时为 null |
| `strategy` | string | `off`/`v1`/`v2` | 是 | raw | 三策略配对 |
| `decision.action` | string/null | `RECOVER`/`STOP`/null | 是 | raw | off 无决策时为 null |
| `decision.reason` | string/null | — | 是 | raw | 同 `reachability.reason` |
| `decision.at_s` | number/null | s（仿真时间） | 是 | raw | 等于 `decision_s` |
| `task.status` | string | `RECOVERED`/`SAFE_STOPPED`/`FAILED`/`NOT_APPLICABLE` | 是 | derived | 见 2.1 |
| `task.final_ee_error_m` | number/null | m | 是 | raw | 末帧末端位置误差 |
| `task.recovery_time_s` | number/null | s | 是 | raw | 恢复耗时，见 B 判据 |
| `task.stop_time_s` | number/null | s | 是 | raw | 进入停稳速度范围耗时 |
| `task.peak_fault_joint_torque_nm` | number/null | N·m | 是 | raw | 故障关节峰值力矩 |
| `task.max_joint_speed_rad_s` | number | rad/s | 是 | raw | 全程峰值关节速度 |
| `task.max_joint_torque_nm` | number | N·m | 是 | raw | 全程峰值关节力矩 |
| `trace.path` | string | 相对或绝对路径 | 是 | raw | `<run_id>.csv.gz` |
| `trace.sha256` | string | 64 位小写十六进制 | 是 | derived | 原始轨迹文件哈希 |
| `trace.frame_count` | integer | 800 | 是 | raw | 实际行数 |
| `trace.sample_rate_hz` | integer | 固定 `100` | 是 | raw | 采样率 |
| `source_sha256` | object | 路径→64 位哈希 | 否 | raw | 算法/配置源码哈希，取自 summary `meta.source_sha256` |

### 2.1 枚举语义

- `reachability.status=REACHABLE`：规划器在 0.02 m 位置容差内找到锁定约束下的解。
- `reachability.status=NO_FEASIBLE_PLAN`：规划器搜索失败，**不等于数学证明不可达**；据此进入停止决策。
- `reachability.status=NOT_ASSESSED`：off/v1 或无故障运行，不声称可达性。
- `task.status`：
  - `RECOVERED`：故障期间末端 ≤0.05 m 并连续保持 0.25 s 至结束，且未发 STOP。
  - `SAFE_STOPPED`：发 STOP 后 2 s 内全部关节速度 ≤0.05 rad/s，并保持 0.25 s 至结束。
  - `FAILED`：注入故障但既未恢复也未安全停止。
  - `NOT_APPLICABLE`：无故障对照运行。

## 3. TraceFrame 记录字段

| 字段 | 类型 | 单位/取值 | 必填 | 来源 | 说明 |
|---|---|---|---|---|---|
| `contract_version` | string | 固定 `2.0.0` | 是 | envelope | 契约版本 |
| `run_id` | string | 32 位小写十六进制 | 是 | raw | 与 Run 一致 |
| `step` | integer | ≥0 | 是 | raw | 控制周期序号，0 起 |
| `timestamp_ms` | integer | Unix 毫秒 | 是 | derived | `started_at_ms + round(t_s×1000)` |
| `sim_time_s` | number | s | 是 | raw | 积分后的实测时刻 `t_s` |
| `command_time_s` | number | s | 是 | raw | 采样/下发时刻 `command_t_s` |
| `joints` | object[6] | 见下 | 是 | raw | 顺序固定 J0–J5 |
| `joints[].name` | string | `^J[0-5]$` | 是 | derived | 与索引一致 |
| `joints[].position_rad` | number | rad | 是 | raw | `q0…q5` |
| `joints[].velocity_rad_s` | number | rad/s | 是 | raw | `qd0…qd5` |
| `joints[].torque_nm` | number | N·m | 是 | raw | `tau0…tau5` |
| `end_effector.position_m` | number[3] | m | 是 | derived | 由 `compute_pose(q)` 前三维得到 |
| `end_effector.rpy_rad` | number[3] | rad | 是 | derived | 由 `compute_pose(q)` 后三维得到，ZYX |
| `ee_error_m` | number | m | 是 | raw | `ee_error_m`，末端位置误差 |
| `fault_active` | boolean | — | 是 | raw | 当前帧故障是否生效 |
| `fault_type` | string/null | `JOINT_LOCKED`/null | 是 | raw | `event_type` |
| `fault_joint` | integer/null | 0–5 | 是 | raw | `event_joint` |
| `action` | string/null | `RECOVER`/`STOP`/null | 是 | raw | 当前决策 |
| `reason` | string/null | — | 是 | raw | 当前决策原因 |

### 3.1 时间坐标

- `sim_time_s` 是离线实验的权威时间轴；`timestamp_ms` 由 `started_at_ms` 平移得到，只用于云端按时间查询。
- MQTT 在线链路仍使用真实 Unix 毫秒时间戳；回放时把轨迹 `t_s` 叠加回放起始 epoch，见 `test/experiments/replay_trace_to_mqtt.py`。
- 检测/决策时刻统一用仿真时间（`s`），避免离线与在线时间基准混用。

### 3.2 末端位姿

- 位置单位 m、姿态单位 rad，姿态顺序为 ZYX 欧拉角 `roll, pitch, yaw`。
- 本轮恢复判据只评价末端**位置**，姿态仅记录，不参与恢复/停止评分。
- 原始 CSV 未直接写入位姿；规范化时用 `edge_node.fault.kinematics.compute_pose(q)` 计算，保证与规划器同一 DH 模型。

## 4. 与 B 验收判据对齐

| 判据 | 冻结值 | 契约落点 |
|---|---:|---|
| 末端位置容差 | 0.05 m | `task.status=RECOVERED` |
| 恢复保持时间 | 0.25 s | `task.status=RECOVERED` |
| 全程边界 | 关节角 ≤π rad、速度 <1.96 rad/s、峰值力矩 ≤50 N·m、故障关节均值 <15 N·m | 评分前置边界 |
| 停止时限 | 2.0 s | `task.status=SAFE_STOPPED` |
| 停止速度阈值 | 0.05 rad/s | `task.status=SAFE_STOPPED` |
| 停止保持时间 | 0.25 s | `task.status=SAFE_STOPPED` |
| 恢复指令速度/加速度上限 | 1.0 rad/s / 2.0 rad/s² | `algorithm_version` 对应配置 |
| 规划器位置容差 | 0.02 m | `reachability.status=REACHABLE` |
| 卡滞检测阈值 | 10.0 N·m | `fault.confirmed` |
| 合成卡滞读数 | 12.5 N·m | `fault` 场景参数 |
| 默认读数噪声 | σ=0 N·m | `scenario`/manifest |
| 控制周期 | 100 Hz | `simulation.control_hz` |

## 5. 与 B 的场景/种子对齐（validation-r1）

- 关节：J0–J3（基座回转、肩、肘、腕），每个关节 6 个场景。
- 注入时刻与种子（按注入档位固定，不随关节/目标变化）：

| 档位 | 注入时刻 | `scenario.seed` | 目标 |
|---|---:|---:|---|
| s1 | 0.40 s | 300 | T1/T2 |
| s2 | 0.80 s | 301 | T1/T2 |
| s3 | 1.20 s | 302 | T1/T2 |

- 规模：4 关节 × 3 档 × 2 目标 = 24 个场景；三策略配对共 72 次运行。
- 场景命名：`VALIDATION-LOCK-J<joint>#s<档>T<目标>`，`run_id` 每次随机生成，不复用。
- validation 目标在运行前冻结，但制定时已可见开发/探索结果；对外表述为「预先冻结留出集」，不称独立盲测。
- 回归期望（r1）：off 11/24 恢复、V1 19/24、V2 21/24 恢复 + 3/24 安全停止；检出率 100%，平均确认延迟 240 ms。

## 6. 字段映射与生成规则

### 6.1 原始 → 规范化

| 规范化字段 | 原始来源 |
|---|---|
| `run_id` | `runs[].run_id`；轨迹文件名 |
| `algorithm_version` | 由 `strategy` 映射（off/v1/v2） |
| `started_at_ms` | 批次运行开始时刻（manifest/执行器记录） |
| `scenario.*` | `scenario`、`seed`、`task_goal_rad`、`description`；`split` 取 `meta.split` |
| `fault.*` | `fault_joint`、`fault_onset_s`、`fault_detection_latency_ms`；`detected_at_s` 由前两者相加 |
| `reachability.*` | `action`、`decision_s`；`reason` 取决策时刻轨迹帧的 `reason`；映射见 2.1 |
| `decision.*` | `action`、`decision_s`；`reason` 取决策时刻轨迹帧的 `reason` |
| `task.*` | `recovered`、`safe_stopped`、`fault_injected`、`final_ee_error_m`、`recovery_time_s`、`stop_time_s`、`peak_fault_joint_torque_nm`、`max_joint_speed_rad_s`、`max_joint_torque_nm` |
| `trace.*` | `trace`、文件 SHA-256、CSV 行数、`meta.sample_rate_hz` |
| 帧 `joints` | `q0…q5`、`qd0…qd5`、`tau0…tau5` |
| 帧 `end_effector` | `compute_pose(q)` |
| 帧 `ee_error_m` | `ee_error_m` |
| 帧 `fault_*`/`action`/`reason` | `fault_active`、`event_type`、`event_joint`、`action`、`reason` |

任务状态映射：

| 原始条件 | `task.status` |
|---|---|
| `fault_injected=false` | `NOT_APPLICABLE` |
| `recovered=true` | `RECOVERED` |
| `safe_stopped=true` | `SAFE_STOPPED` |
| 以上均不满足 | `FAILED` |

可达性映射：

| 原始条件 | `reachability.status` |
|---|---|
| `action=RECOVER` | `REACHABLE` |
| `action=STOP` 且 `reason=NO_FEASIBLE_PLAN` | `NO_FEASIBLE_PLAN` |
| off/v1 或无决策 | `NOT_ASSESSED` |

### 6.2 `started_at_ms` 的确定

离线基准不写墙钟。`started_at_ms` 是**批次时间基准**，不是物理启动瞬间：优先取执行器启动日志；没有日志时取 manifest 的 `generatedAt`（批次完成时刻）作保守基准，并在 manifest 用 `timeBaseSource` 标注来源。

- r1 的基准值：`1795660686017`（`2026-11-26T10:38:06.017+08:00`），来源见 manifest 的 `timeBaseMs` / `timeBaseSource`。
- 帧 `timestamp_ms = started_at_ms + round(sim_time_s×1000)`，只用于云端按时间查询；`sim_time_s` 仍是权威仿真时间。
- 禁止用入库时的当前时间逐条伪造时间戳。

## 7. 版本与兼容

| 版本 | 日期 | 变更 |
|---|---|---|
| 2.0.0 | 2026-11-26 | 首次冻结：run + trace frame、B 判据/种子对齐、schema 与夹具 |

- `contract_version` 采用语义化版本：
  - MAJOR：删除/重命名字段、改类型/单位/枚举语义；
  - MINOR：新增可选字段；
  - PATCH：文档纠正，不改结构。
- 任何结构变更必须同时更新：本文件、两份 schema、`test/fixtures/v2_contract/`、`test/test_v2_contract.py`，并通知 A/B。
- B 的 validation-r1 原始记录不再改写；新版本用新 `contract_version` 重跑或迁移。
- MQTT `RobotState`/`Heartbeat` 字段不变；V2 契约属于实验记录层，不新增 MQTT topic。

## 8. 已知边界

- `NO_FEASIBLE_PLAN` 只表示规划器搜索失败，不是不可达的数学证明。
- 末端位姿仅记录，评分只用到末端位置误差。
- validation-r1 不是独立盲测；数字只适用于 Python plant 的仿真条件，详见 [ROS 2 降级说明](v2-ros2-fallback.md)。
- 原始轨迹体积大，不入 Git；按 `run_id` 在本地留存，manifest 记录路径与哈希。
