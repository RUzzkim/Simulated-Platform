# V2.0 单关节卡滞实验 —— 阶段性汇总（成员 C）

- 日期：2026-11-26
- 分支：`develop-C`（本地领先 8 个提交，未推送）
- 契约版本：`2.0.0`（完成态冻结，另有实时辅助 schema）
- 对齐基线：成员 B 的 validation-r1（24 场景、种子 300/301/302、恢复 0.05 m + 0.25 s、停止 2 s + 0.05 rad/s、规划容差 0.02 m、锁定检测 10 N·m、合成 12.5 N·m）

## 1. 结论摘要

端→边→云链路已贯通：仿真 `sim_state` 经边端滤波、故障检测、容错决策后，故障事件、决策事件、`run_id` 与实验 Run 一并入库，页面可按 `run_id` 查询事件时间线与曲线，并导出 JSON/CSV 归档。

ROS 2/Gazebo 物理链路本机未能跑通，按 `docs/v2-ros2-fallback.md` 降级为 Python plant 确定性实验；该降级不影响契约字段与判据，但**在线闭环控制未演示**。

## 2. 数据流与主题

```
仿真端 --sim_state/joint_states--> 边端(滤波→检测→容错→决策) --experiment_run/experiment_event/sim_state-->
MQTT(mTLS 8884) --> 云端(Spring Boot) --> MySQL(experiment_run / experiment_event / 遥测) --> REST --> Vue 页面
```

| 主题 | 方向 | 说明 |
|---|---|---|
| `simulation/{sim}/sim_state` | 边←仿真 | 原始状态；边端只读 |
| `simulation/{sim}/state` | 边→云 | 处理后状态（含可选 `faults`） |
| `simulation/{sim}/heartbeat` | 边→云 | 心跳与 LWT 下线通知 |
| `simulation/{sim}/command`、`command_ack` | 云↔边 | 控制命令与应答 |
| `simulation/{sim}/experiment_run` | 边→云 | 实验 Run（启动 `IN_PROGRESS`、退出 `INCOMPLETE`） |
| `simulation/{sim}/experiment_event` | 边→云 | 故障/决策事件，幂等键 `run_id\|event_type\|timestamp\|joint\|action` |

## 3. 契约与 schema

| 文件 | 内容 |
|---|---|
| `v2_run.schema.json` | 离线完成态 Run（`RECOVERED`/`SAFE_STOPPED`/`FAILED`/`NOT_APPLICABLE`） |
| `v2_trace_frame.schema.json` | 每控制周期一帧，含关节量、末端位姿、误差、故障标志 |
| `v2_experiment_event.schema.json` | `FAULT`/`DECISION` 事件 |
| `v2_live_run.schema.json` | 实时部分 Run（仅 `IN_PROGRESS`/`INCOMPLETE`，`fault`/`decision` 为空、`trace.path=live://<run_id>`） |

位置：`edge/edge_node/docs/contract/`，说明见 `docs/v2-experiment-contract.md`。

**版本决策**：实时状态不并入完成态 schema，避免牵动 A/B 判据；完成态契约保持 `2.0.0` 冻结，实时记录由辅助 schema 独立校验，两者交叉拒绝（见 `test_v2_contract.py`）。

## 4. 云端接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/experiments/runs?page=&size=&status=&runId=&deviceId=` | Run 分页与筛选 |
| GET | `/api/experiments/runs/{runId}` | Run 详情（索引列回填 fault/reachability/decision/task） |
| GET | `/api/experiments/runs/{runId}/events` | 故障/决策事件时间线 |
| GET | `/api/experiments/runs/{runId}/series?limit=800&downsample=false` | Run 时间窗内遥测曲线 |
| GET | `/api/experiments/runs/{runId}/export?format=json\|csv` | JSON：Run+事件归档；CSV：事件时间线 |

表结构：`experiment_run`、`experiment_event`，迁移脚本 `docs/migrate-v8-experiment.sql`。

## 5. 前端

路由 `/experiments`（导航「实验回放」）：列表筛选分页、详情弹窗、故障/决策时间线、位置/速度/力矩/末端误差曲线、JSON/CSV 导出。状态含 `IN_PROGRESS: 运行中`、`INCOMPLETE: 未完成`。

## 6. 验证记录

| 项目 | 结果 |
|---|---|
| 契约测试 `test_v2_contract.py` | 11 例通过（Run/Frame/Event/Live 四套 schema + 交叉校验） |
| 后端单测 `ExperimentServiceIngestTest` | 6 例通过（快照合并、完成态覆盖、事件回填、幂等） |
| 优雅退出 e2e `test_graceful_exit_e2e.py` | 1 例通过（真实边端 payload 过 live schema，`IN_PROGRESS→INCOMPLETE`，退出码 0） |
| 前端单测（Vitest） | 6 例通过（四个查询接口 + 两个导出） |
| 前端构建 | `npm run build` 通过 |
| 接口实测 | 导出 JSON 1806 B（`contract=2.0.0`、`INCOMPLETE`、`JOINT_LOCKED`、2 事件）；CSV 表头 + 2 行 |
| 浏览器 | 登录 → `/experiments` → 详情，两个导出按钮可见、无报错 |

关键 `run_id`：

| run_id | 用途 |
|---|---|
| `e3529e78…` | 离线轨迹回放导入（800 帧曲线 + 2 事件） |
| `f099db45…` | 优雅退出验证（SIGBREAK → INCOMPLETE） |
| `213e81e5…` | OFFLINE 心跳修复后复验 |
| `87cdcd88…` | 实时决策一键演示（FAULT + DECISION，导出口径样例） |

## 7. 已知边界

- **ROS 2/Gazebo 未验证**：本机无 ROS 2 环境，链路与在线闭环控制未演示；降级理由与适用范围见 `docs/v2-ros2-fallback.md`。
- **实时 Run 是部分记录**：只带启动快照与状态变更，不写 `trace` 文件（`live://` 占位），完成态判据不适用。
- **原始轨迹不入库**：11.3 MB CSV 仅本地保存并已 gitignore，入库的是规范化 Run/事件与遥测。
- **本地库有演示数据**：`experiment_run` 中留有少量演示 Run，需要干净环境时手工清理。
- **测试覆盖粒度**：后端仅服务层单测，前端仅 API 层单测，组件与端到端 UI 断言未覆盖。

## 8. 复现步骤

```powershell
# 本地栈（仓库根目录）
cd deploy
docker compose -f docker-compose.local.yml up -d

# 边端（无 ROS 2 模式）
cd ..\edge\edge_node
py -B -m edge_node.main --config config\edge_config.yaml

# 测试
py -B test/test_v2_contract.py -v
py -B test/start_mqtt_broker.py        # 另开终端
py -B test/test_graceful_exit_e2e.py -v
cd ..\..\frontend; npm test
```

## 9. 待办

1. 有 ROS 2 环境时补验 `ros2-gazebo` plant 与在线闭环，产出对照 Run。
2. 如需实时 Run 也进入完成态验收，另提契约 MINOR 升级（`2.1.0`）并同步 A/B。
3. 组件级/端到端 UI 自动化测试按需补充。
