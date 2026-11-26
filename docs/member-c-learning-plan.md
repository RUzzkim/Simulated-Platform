# 组 C（边缘/云集成）学习计划表

- 适用：组 C 成员及接手端—边—云链路的人
- 起始：2026-11-26（对齐 `docs/v2.0-development-proposal.md` 阶段：11/26 环境基线 → 11/28 接口冻结 → 12/03 算法 → 12/06 集成 → 12/09 冻结交付）
- 投入建议：每周 8–10 小时，每天 60–90 分钟（30 分钟阅读 + 45 分钟动手 + 15 分钟记录）
- 前置要求：Python 基础、Git 基本操作；不要求 ROS 2 经验
- 目标：能独立维护 MQTT 链路、契约与 schema、运行配置、端到端测试，并产出交付材料

## 1. 四周路线

| 周次 | 日期 | 主题 | 过关标志 |
|---|---|---|---|
| 第 1 周 | 11/26–11/28 | 链路与契约 | 能解释一条状态从仿真到页面的完整路径 |
| 第 2 周 | 11/29–12/03 | 云端、前端与测试 | 能改一处后端/前端并通过测试 |
| 第 3 周 | 12/04–12/06 | 集成与回放 | 能独立完成一次全链路联调 |
| 第 4 周 | 12/07–12/09 | 交付与复盘 | 能产出报告/演示材料并复核数字 |

## 2. 第 1 周：链路与契约

| 天 | 主题 | 学什么 | 动手 | 自测 |
|---|---|---|---|---|
| D1 | MQTT 与 mTLS | 发布/订阅、QoS、遗嘱 LWT、双向 TLS | 起测试 broker，订阅 `simulation/SIM-001/state` 观察消息 | 说明 `sim_state` 与 `state` 为何分开、LWT 作用 |
| D2 | 契约阅读 | `v2-experiment-contract.md` 第 1–3 节；raw/derived/envelope 三类来源 | 对照 schema 找一个字段的全部出现位置 | 说出 `run_id` 在哪些环节被使用 |
| D3 | Docker 本地栈 | compose 服务、卷挂载、健康检查、nginx 反代 | `up -d` 起栈，登录看 `/experiments` | 说清 8090/8091/8884 各是什么 |

代码入口：`edge/edge_node/edge_node/mqtt/mqtt_client.py`、`edge/edge_node/docs/contract/`、`deploy/docker-compose.local.yml`、`deploy/nginx/default.conf.template`

## 3. 第 2 周：云端、前端与测试

| 天 | 主题 | 学什么 | 动手 | 自测 |
|---|---|---|---|---|
| D4 | Spring Boot 分层 | Controller/Service/Repository/Entity；JPA 与索引列 | 读 `ExperimentService.runView`，改一处回填逻辑并跑单测 | 说明为什么列值要回填嵌套对象 |
| D5 | JSON Schema | draft-07 的 `const`/`enum`/`pattern`/`if-then` | 新增一个非法夹具让测试变红，再修好 | 能手工写出一个合法 FAULT 事件 |
| D6 | Vue 3 + Vitest | Composition API、axios 封装、blob 下载 | 给导出按钮加 loading 态并补一条单测 | 说清前端如何携带 JWT |
| D7 | e2e 调试 | 子进程、MQTT 观察者、信号与退出码 | 跑 `test_graceful_exit_e2e.py`，改坏断言再恢复 | 解释 `IN_PROGRESS→INCOMPLETE` 何时发生 |

代码入口：`backend/.../experiment/`、`frontend/src/views/Experiments.vue`、`frontend/src/api/`、`edge/edge_node/test/`

## 4. 第 3 周：集成与回放

| 天 | 主题 | 学什么 | 动手 | 自测 |
|---|---|---|---|---|
| D8 | 时间窗 | `started_at_ms` 与遥测时间戳的映射 | 查 `/series` 为空时定位原因（窗口/降采样/run_id） | 说出三种空曲线根因 |
| D9 | 导出 | CSV 转义、`Content-Disposition`、JSON 归档结构 | 改导出内容并验证下载文件名 | 说明 JSON 与 CSV 各自用途 |
| D10 | 可观测性 | 日志分级、心跳与 LWT 排障 | 制造一次断线，读日志定位 | 说出下线通知与心跳的区别 |
| D11 | 全链路演练 | 故障注入 → 检测 → 决策 → 入库 → 页面 → 导出 | 用 `live_decision_demo.py` 走一遍并计时 | 全程独立完成不查步骤 |

## 5. 第 4 周：交付与复盘

| 天 | 主题 | 学什么 | 动手 |
|---|---|---|---|
| D12 | 报告结构 | 结论标注仿真条件、样本与分布、失败案例 | 搭报告骨架，数字留空位 |
| D13 | 演示录屏 | 分镜：故障 → 决策 → 结果 → 导出 | 录制 3–5 分钟演示 |
| D14 | 数字复核 | 每个结论回指 `run_id` 与原始数据位置 | 抽查 5 条结论的可追溯性 |
| D15 | 复盘交接 | 已知边界、待办、环境依赖 | 更新 `docs/v2-summary.md` |

## 6. 每日节奏（建议）

```
30 min  阅读官方文档或本仓库文档（只读一节，做一句话笔记）
45 min  动手：改一处代码 + 跑对应测试（pytest / npm test）
15 min  记录：今天学了什么 / 卡在哪 / 明天第一件事
```

## 7. 过关自测清单

- [ ] 不查文档说出 Run 与 TraceFrame 的关系
- [ ] 手工构造一个合法 `FAULT` 事件并通过 `v2_experiment_event.schema.json`
- [ ] 定位一次「页面无曲线」的根因（时间窗 / `run_id` / 降采样）
- [ ] 独立跑通 `py -m pytest test -q` 与 `npm test`
- [ ] 在不破坏 2.0.0 契约的前提下新增字段（说明走什么版本流程）
- [ ] 解释实时部分 Run 为什么用独立辅助 schema

## 8. 资源

- MQTT：Eclipse Mosquitto 文档、MQTT 5.0 规范第 3–4 章
- 云端：Spring Boot 3 Reference、Spring Data JPA 文档
- 契约：JSON Schema draft-07 官方文档
- 前端：Vue 3 官方指南、Vitest 指南
- 仓库内：[契约](v2-experiment-contract.md)、[ROS 2 降级说明](v2-ros2-fallback.md)、[阶段汇总](v2-summary.md)、`docs/SETUP_CONTEXT.md`

## 9. 可选：ROS 2 入门（有环境时再学，2 小时）

- `ros2 topic list/echo`、`rclpy` 节点生命周期、`joint_states` 消息结构
- 对照 `edge_node` 的 ROS 2 分支，理解与 Python plant 的差异
- 注意：本机无 ROS 2 环境时跳过，不影响 C 的其余职责
