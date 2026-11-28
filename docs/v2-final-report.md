# V2.0 单关节卡滞任务恢复 —— 技术报告（定稿）

- 版本：定稿（2026-11-28）
- 责任方：成员 C（端边云集成与可追溯性）；算法与仿真由成员 B 提供
- 契约版本：`2.0.0`（完成态冻结）
- 分支：`develop-C`
- 适用范围声明：全部结论来自 **Python plant 确定性仿真**（`plant=python-6r`，控制周期 10 ms，合成卡滞力矩读数 12.5 N·m），**非工业现场实测、非 ROS 2/Gazebo 物理链路**，不可外推为盲测性能估计。

## 1. 背景与目标

工业机械臂单关节执行器卡滞会使末端偏离目标并可能持续过负荷。V2.0 验证在卡滞发生后，边端能否检测故障、判断任务目标是否仍可达，并在可达时重规划健康关节、不可达时安全停止，且全过程不越界。

本报告回答：
1. off / v1 / v2 三策略在 24 个冻结验证场景下的恢复成功率差异；
2. 恢复耗时、停稳耗时、峰值力矩等关键指标的分布；
3. 端→边→云链路是否让每个 `run_id` 的事件、曲线、导出都可追溯；
4. 结论的仿真条件与已知边界。

## 2. 系统组成与数据流

```
仿真端 --sim_state/joint_states--> 边端(滤波→检测→容错→决策) --experiment_run/experiment_event/state-->
MQTT(mTLS 8884) --> 云端(Spring Boot) --> MySQL --> REST --> Vue 页面
```

| 主题 | 方向 | 说明 |
|---|---|---|
| `simulation/{sim}/sim_state` | 边←仿真 | 原始状态，边端只读 |
| `simulation/{sim}/state` | 边→云 | 处理后状态（可选 `faults`） |
| `simulation/{sim}/heartbeat` | 边→云 | 心跳与 LWT 下线通知 |
| `simulation/{sim}/command`、`command_ack` | 云↔边 | 控制命令与应答 |
| `simulation/{sim}/experiment_run` | 边→云 | 实验 Run（启动 `IN_PROGRESS`、退出 `INCOMPLETE`） |
| `simulation/{sim}/experiment_event` | 边→云 | 故障/决策事件，幂等键 `run_id\|event_type\|timestamp\|joint\|action` |

## 3. 契约与判定

完成态契约 `2.0.0` 冻结于 `edge/edge_node/docs/contract/`，四套 schema：离线完成态 Run、每帧 trace、`FAULT`/`DECISION` 事件、实时部分 Run（`live://` 占位）。实时状态不并入完成态 schema，两者交叉拒绝（见 `test_v2_contract.py`，11 例通过）。

| 评分判据（来源：B 的 `member-b-task-recovery.md`） | 计算方法 |
|---|---|
| 恢复 | 卡滞期间末端距目标 ≤ 0.05 m，连续至少 0.25 s 并保持至结束 |
| 停稳 | STOP 下发后 2 s 内所有关节速度 ≤ 0.05 rad/s 并保持 ≥ 0.25 s |
| 全程边界 | `\|q\| ≤ π`、`\|qd\| < 1.96 rad/s`、峰值力矩 ≤ 50 N·m、故障关节故障期间平均绝对力矩 < 15 N·m |
| 确认延迟 | 注入至检测器首次报告同一关节 `JOINT_LOCKED`（仿真时间） |

> 判据来源：`docs/member-b-task-recovery.md` §方法和判据；`docs/member-b-failure-analysis.md` §实验口径。

## 4. 方法（三策略）

| 策略 | 行为 |
|---|---|
| off（容错关闭） | 不检测、不补偿，原轨迹自然执行；作为基线 |
| v1 | 检测故障但不规划，仅透传/制动；无 RECOVER/STOP 决策 |
| v2 | 检测确认卡滞后固定故障关节，以原任务终点三维位置为目标对健康关节做带限位阻尼最小二乘搜索（位置误差容差 0.02 m）；搜索失败输出 `NO_FEASIBLE_PLAN` 并锁存 STOP。健康关节速度上限 1.0 rad/s、加速度上限 2.0 rad/s² |

方法表述依据：`docs/member-b-task-recovery.md` §方法和判据；`docs/v2-strategy-comparison.md`。

## 5. 实验设置

- 场景：4 故障关节（J0–J3）× 3 注入时刻（0.40 / 0.80 / 1.20 s）× 2 点到点任务（T1/T2）= **24 场景**。
- 策略配对：每场景各跑 off / v1 / v2 一次，共 **72 次运行**。
- 场景种子：300 / 301 / 302（与注入时刻一一对应，**seed 与 onset 完全混淆**，方差不可分离；见 `docs/v2-strategy-comparison.md` §0）。
- 仿真：8 s / 次，步长 0.01 s（100 Hz），确定性模型，无随机数。
- 合成卡滞力矩读数：12.5 N·m（高于检测阈值 10 N·m，低于评分上限 15 N·m）。
- 数据来源：B 的冻结验证集 `docs/member-b-validation-frozen-r1.json`（72 runs，含逐次 `run_id`、`trace`、源码 SHA-256）；C 侧复现 `edge/edge_node/test/experiments/data/official-validation-r1/summary.json`。

> 验证集目标在运行前已固定，但制定时已查看开发/探索集结果，**不构成独立盲测**，作为版本回归基准报告。

## 6. 结果

### 6.1 恢复成功率（24 场景分母）

| 策略 | 恢复 | 安全停稳 | 失败 | 恢复率 |
|---|---:|---:|---:|---:|
| off | 11 | 0 | 13 | 45.8% |
| v1 | 19 | 0 | 5 | 79.2% |
| v2 | 21 | 3 | 0 | 87.5% |

来源：`docs/member-b-validation-frozen-r1.json` `summary`；C 侧复现核对一致（`docs/v2-strategy-comparison.md`）。

### 6.2 关键指标（v2，来源：B frozen-r1 逐次字段）

| 指标 | 取值 | 口径 |
|---|---|---|
| 故障确认延迟 | 240 ms（24/24 一致） | `fault_detection_latency_ms` |
| 恢复耗时 | p50 1.11 s，min 0.26 s，max 2.86 s（n=21） | `recovery_time_s` |
| 停稳耗时 | 0.04 / 0.19 / 0.22 s（n=3） | `stop_time_s` |
| 全程峰值关节速度 | ≤ 1.000 rad/s | `max_joint_speed_rad_s` |
| 故障关节峰值力矩 | 12.5 N·m | `peak_fault_joint_torque_nm` |
| v2 决策覆盖 | 24/24 均记录故障确认与动作（21 RECOVER + 3 STOP） | `action` / `event_type` |

### 6.3 按故障关节（v2，B frozen-r1）

| 关节 | 恢复 | 安全停稳 |
|---|---:|---:|
| J0 基座回转 | 3/6 | 3/6 |
| J1 肩部/大臂俯仰 | 6/6 | 0/6 |
| J2 肘部/小臂俯仰 | 6/6 | 0/6 |
| J3 腕部回转 | 6/6 | 0/6 |

### 6.4 系统指标（C 侧采集汇总，72 条 trace，57,600 帧）

| 指标 | 结果 |
|---|---|
| 仿真控制周期 | p50 / p95 / p99 / max 均为 10.000 ms（目标 100 Hz） |
| 轨迹缺帧 | 0 / 57,600（0.0000%） |
| 安全边界有界 Run | 72 / 72（位置、速度、力矩全程无越界） |
| 峰值速度 Run 分布 | p50 0.593、p95 0.910、max 1.000 rad/s |
| 峰值力矩 Run 分布 | p50 12.500、p95 12.500、max 17.827 N·m |
| 末 1 s 速度 RMS | p50 0.0004、p95 0.0047、max 0.0066 rad/s |

来源：`docs/v2-system-metrics.md`（脚本 `edge/edge_node/test/experiments/analyze_metrics.py`）。
口径边界：周期来自仿真时间 `t_s`，**不是墙钟调度周期**；缺帧按 `step` 核查轨迹连续性，**不等同于 MQTT 网络丢包**（当前契约无应用层 `seq`，真实丢包需另加序号或抓包）。

## 7. 失败案例（v2，3 例 STOP）

v2 无 FAILED，3 例为搜索未找到恢复方案后触发安全停止，全部集中在 J0（基座回转）卡滞的 T2 任务：

| run_id | 场景 | 注入时刻 | 决策 | stop_time_s |
|---|---|---:|---|---:|
| `8dd01c26…` | VALIDATION-LOCK-J0#s1T2 | 0.4 s | STOP | 0.19 |
| `7090fd83…` | VALIDATION-LOCK-J0#s2T2 | 0.8 s | STOP | 0.22 |
| `1ab28897…` | VALIDATION-LOCK-J0#s3T2 | 1.2 s | STOP | 0.04 |

来源：`docs/member-b-validation-frozen-r1.json` `runs[]`（`strategy=v2` 且 `safe_stopped=true`）。
说明：`NO_FEASIBLE_PLAN` 仅表示当前数值搜索范围与判据下未找到解，**不构成目标不可达的数学证明**；停止分支由搜索失败触发，应表述为“未找到恢复方案后安全停止”（见 `docs/member-b-failure-analysis.md` §限制）。

## 8. 可追溯性

每个数字可回指：
- 逐次结果：`docs/member-b-validation-frozen-r1.json` `runs[]`，每条含 `run_id`、`trace`、`recovered`、`safe_stopped`、`recovery_time_s`、`stop_time_s`、`fault_detection_latency_ms` 及源码 `source_sha256`。
- C 侧入库核对：72 条 validation Run 全部入库，`manifest ↔ DB ↔ trace.sha256` 72/72 一致（`docs/member-c-plan.md` §4.4 G-3）。
- 云端可按 `run_id` 查询：详情、事件时间线、遥测曲线（默认 800 点 / 8 s）、JSON/CSV 导出（`docs/member-c-plan.md` §4.4 G-2、G-4；接口见 `docs/v2-summary.md` §4）。
- 系统指标复算：`py -3 edge/edge_node/test/experiments/analyze_metrics.py --summary edge/edge_node/test/experiments/data/official-validation-r1/summary.json`。

## 9. 边界与风险

1. **ROS 2/Gazebo 未验证**：本机无 ROS 2 环境，在线闭环控制与 `plant=ros2-gazebo` 未演示，按 `docs/v2-ros2-fallback.md` 降级为 Python plant。该降级不影响契约字段与判据，但物理链路结论缺失。
2. **非盲测**：验证集目标在先前数据可见后制定，结果作为版本回归基准，不构成性能估计或外推。
3. **实时 Run 为部分记录**：只带启动快照与状态变更，不写 trace 文件（`live://` 占位），完成态判据不适用。
4. **轨迹缺帧 ≠ 网络丢包**：详见 §6.4 口径边界；真实 MQTT 丢包/重传需应用层序号或 broker/订阅端抓包。
5. **seed/onset 混淆**：种子方差与注入时刻方差不可分离（`docs/v2-strategy-comparison.md` §0），已提请 B 确认是否有意为之。
6. **原始轨迹不入库**：大体积 CSV 仅本地保存并 gitignore，入库的是规范化 Run/事件与遥测。

## 10. 复现步骤

```powershell
# 1. 起本地栈（backend / mysql / mosquitto / nginx）
cd deploy
docker compose -f docker-compose.local.yml up -d

# 2. 复算三策略对照（输出 docs/v2-strategy-comparison.md）
cd ..
py -3 edge/edge_node/test/experiments/analyze_strategies.py `
  --summary edge/edge_node/test/experiments/data/official-validation-r1/summary.json `
  --out docs/v2-strategy-comparison.md

# 3. 复算系统指标（输出本报告 §6.4）
py -3 edge/edge_node/test/experiments/analyze_metrics.py `
  --summary edge/edge_node/test/experiments/data/official-validation-r1/summary.json `
  --out docs/v2-system-metrics.md

# 4. 复现 B 冻结验证集（24 场景 × 3 策略 = 72 runs）
py -3 edge/edge_node/test/benchmarks/run_task_recovery.py --split validation `
  --output-dir edge/edge_node/test/reports/task_recovery/member-b-validation-frozen-r1 `
  --json docs/member-b-validation-frozen-r1.json

# 5. 全量边缘测试（依赖 broker）
py -3 -m pytest edge/edge_node/test -q
```

## 附：数字复核检查表

| # | 检查项 | 状态 |
|---|---|---|
| 1 | 每个统计量可定位到 Run 或汇总文件 | ✅（§6–§8 均标注来源） |
| 2 | 场景条件完整（关节/注入时刻/容差/种子） | ✅（§5） |
| 3 | 仿真条件标注（Python plant / 100 Hz / 12.5 N·m） | ✅（文首 + §5） |
| 4 | 成功率注明样本数与分母（24） | ✅（§6.1） |
| 5 | 失败案例单列，不并入成功 | ✅（§7，3 STOP 单独列出，v2 无 FAILED） |
| 6 | 停止与恢复分开统计 | ✅（§6.1 恢复率不含停稳） |
| 7 | 数字与图表一致 | ✅（单一数据源，无图表） |
| 8 | 无越界表述（不声称工业实测/普适比例） | ✅（文首声明 + §9） |
