# V2.0 ROS 2 链路降级说明：Python plant 确定性实验

- 状态：已冻结
- 冻结日期：2026-11-26
- 责任：成员 C（边缘/云集成）
- 适用范围：V2.0 validation-r1 及后续离线对照实验
- 关联契约：[V2 实验契约](v2-experiment-contract.md)

## 1. 结论

本机没有跑通 ROS 2 端到端链路。V2.0 的核心定量实验改用 **Python plant + 边缘算法离线基准** 完成；MQTT/TLS 的「端→边→云」链路用一条 validation 轨迹回放单独验证。云端在本阶段只承担记录、查询和展示，不作为控制性能或实时性的证据。

这不是把两条链路视为等价：ROS 2 话题、中间件时序和 Gazebo 物理仍未验证；离线基准的结论只适用于第 4 节列出的仿真条件。

## 2. 事实与证据

- `sim/gazebo_arm/README.md` 明确写明本机是 Windows、无 ROS 2，需要在 `ros:humble` 容器内运行。
- 2026-11-26 10:49:20 边端启动日志：`rclpy 不可用，将以无 ROS 2 模式运行（仅 MQTT 链路可测）`，同一轮 MQTT mTLS 连接 `ssl://127.0.0.1:8884` 成功。
- 本机 Docker 可用，`deploy/docker-compose.local.yml` 的 mysql/mosquitto/backend/nginx 四个容器已拉起；回放 800 帧 `sim_state` 后，边端检出 `JOINT_LOCKED joint=0`，云端 `ROBOT-001` 写入 374 行遥测（367 行 `ERROR`）。
- 官方 validation 在远程提交 `a0a6b3b` 的冻结文件上复跑：24 个场景 × off/v1/v2 共 72 次运行，Python 3.14 + 纯 Python plant，结果与冻结文件逐项一致。
- 逐次证据：[实验报告](../edge/edge_node/test/reports/v2_recoverability_report.md)、[批次 manifest](../edge/edge_node/test/experiments/data/official-validation-r1/manifest.json)、[冻结验证集](member-b-validation-frozen-r1.json)、[回放脚本](../edge/edge_node/test/experiments/replay_trace_to_mqtt.py)。

## 3. 降级理由

1. **环境不可用**：本机未安装 ROS 2 发行版，Gazebo 图形与物理稳定性也不满足连续实验要求；临时搭建 ROS 2 容器不能消除物理引擎的非确定性。
2. **实验目标在算法层**：本阶段要回答的是单关节卡滞后「目标是否仍可完成、恢复还是停止」，检测器、可达性规划和容错控制都在 Python 边缘代码中，ROS 2 只是传输层。
3. **确定性优先**：Python plant 固定 100 Hz 步长、固定初始位姿、固定场景种子，同一 `run_id` 可逐帧复核；这是冻结判据和 72 次配对比较的前提。
4. **与 B 的冻结验证集一致**：B 的 validation-r1 判据、场景和种子本身就是在该 Python plant 上冻结的；换用 ROS 2/Gazebo 会引入未冻结的模型差异，反而破坏可比性。
5. **传输层可单独验证**：MQTT/TLS 链路不依赖 ROS 2，已用回放把「故障状态→边端→云端入库」跑通，因此不必为了传输验证阻塞算法实验。

## 4. 降级后的适用范围

### 4.1 成立

| 项目 | 说明 |
|---|---|
| 故障检测与确认 | 与在线边端相同的 `CompositeFaultDetector`，阈值 10 N·m、确认窗口 20/5 |
| 可达性判断与健康关节重规划 | 与在线边端相同的 `RecoveryPlanner`，位置容差 0.02 m |
| 恢复/安全停止决策 | 冻结判据：末端 0.05 m、保持 0.25 s；停止 2 s 内速度 ≤0.05 rad/s |
| 100 Hz 控制周期 | 仿真时间固定步长 0.01 s，记录 800 帧/次 |
| MQTT/TLS 传输与云端入库 | 已用回放验证，含 mTLS、ACL、入库与状态字段 |
| 逐次可追溯 | `run_id`、代码/配置 SHA-256、场景/种子/阈值、原始 CSV |

### 4.2 不成立或未覆盖

| 项目 | 边界 |
|---|---|
| ROS 2 话题与中间件 | 未验证 `joint_states`/`joint_command` 的实际时延、丢帧和 QoS 行为 |
| Gazebo 物理与接触 | 未覆盖碰撞、摩擦、抓取和接触力 |
| 真实机械臂/PLC/现场网络 | 不在本阶段范围 |
| 云端闭环控制时延 | 云端只记录与展示；回放不构成闭环实时性证据 |
| 硬件传感器噪声 | 默认 σ=0；噪声实验单独标注，不外推到实机 |
| 独立盲测 | validation 目标在运行前冻结，但制定时已可见开发/探索结果，不称独立盲测 |

## 5. 成果数字的仿真条件

- 被控对象：通用 6R Python plant，DH 几何 + 简化动力学，位置伺服；无 Gazebo。
- 采样：100 Hz，单次 8 s，800 帧；每次运行独立 `run_id`。
- 场景：validation 4 个故障关节（J0–J3）× 3 个注入时刻（0.40/0.80/1.20 s）× 2 个目标，共 24 个；种子 300/301/302 按注入档位分配。
- 策略：容错关闭 / V1 / V2 三策略配对，共 72 次。
- 故障：`JOINT_LOCKED`，合成卡滞反作用力矩读数 12.5 N·m（高于 10 N·m 检测阈值，低于 15 N·m 故障关节均值上限），默认无读数噪声。
- 冻结结果：off 11/24 恢复；V1 19/24；V2 21/24 恢复 + 3/24 安全停止；检出率 100%，平均确认延迟 240 ms。
- 上述数字只描述该仿真条件下的算法表现，不构成 ROS 2、Gazebo 或工业现场的性能结论。

## 6. 验收映射（V2 提案第 8 节）

| 验收项 | 当前状态 |
|---|---|
| 1. 新成员按文档启动闭环并复现一个卡滞场景 | Docker + MQTT 回放可复现；ROS 2 路径未打通，按本条部分满足 |
| 2. 同场景 A/B/C 三策略、每次有 `run_id` 和原始记录 | 满足，72 次运行均有 manifest 与 800 帧轨迹 |
| 3. 至少一个可达、一个不可达案例，判据冻结 | 满足，J0 含 3 个不可达/停止案例 |
| 4. 报告样本数、分布、失败案例与数据位置 | 满足，见报告第 3–5 节 |
| 5. 演示故障、决策、恢复/停止及结果 | 离线基准 + 云端 V2 记录/事件/曲线回放可演示；V2 在线闭环仍未演示 |
| 6. 性能结论标注仿真条件 | 满足，本文件与报告均标注 |

## 7. 恢复 ROS 2 路径的条件

满足以下全部条件后，才把 ROS 2 结果并入 V2 结论：

1. 在 `ros:humble` 容器内启动 `sim/gazebo_arm`，确认 `joint_states` 稳定发布。
2. 边端使用 ROS 2 输入/输出，跑通一个 `LOCK-J1` 场景并保留 `run_id`。
3. 用同一冻结判据比较 ROS 2 与 Python plant 的检测延迟、末端误差和停止时间，记录差异。
4. 更新本文件、实验契约和报告；在差异未解释前，不把两组数字合并统计。

## 8. 复现与证据

```powershell
# 离线 validation 复跑
py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation `
  --output-dir edge/edge_node/test/reports/task_recovery/validation-repro-r1 `
  --json edge/edge_node/test/reports/task_recovery/validation-repro-r1/summary.json

# 契约与夹具测试
py -m unittest discover -s edge/edge_node/test -p "test_v2_contract.py"

# 本地栈与回放（需 Docker）
docker compose -f deploy/docker-compose.local.yml up -d
py edge/edge_node/test/experiments/replay_trace_to_mqtt.py <trace.csv.gz> `
  --ca deploy/certs/ca.crt --cert deploy/certs/edge/edge-SIM-001.crt `
  --key deploy/certs/edge/edge-SIM-001.key
```

回放时间窗、边端检出时刻和云端行数记录在 manifest 的 `cloudReplay` 字段；原始轨迹按 `run_id` 保存在本地，不入 Git。

## 9. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-26 | 首次冻结 ROS 2 降级理由、适用范围与验收映射 |
