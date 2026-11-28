# 组 C（边缘/云集成）工作计划书

- 版本：v1（2026-11-26）
- 责任：成员 C
- 依据：`docs/v2.0-development-proposal.md`（里程碑与验收标准）、`docs/v2-experiment-contract.md`（契约 2.0.0）
- 用途：C 侧工作的唯一任务板，替代分散在对话与文档中的零散待办

## 1. 目的与范围

覆盖 C 的三类职责：

1. 链路与集成：Docker / MQTT / 边端 / 云端 / 页面贯通
2. 契约与数据：字段冻结、schema、入库、查询、导出
3. 交付与材料：测试维护、复现走查、报告与演示、数字复核

不含：算法实现（B）、仿真场景设计（A）、评价协议本身（B）。

## 2. 现状快照（2026-11-26）

| 维度 | 现状 |
|---|---|
| 代码 | `develop-C`，**领先 `origin/develop-C` 18 个提交，未推送**；工作区干净 |
| 链路 | Docker 四容器健康；MQTT mTLS 正常；边端→云→页面全链路可复现 |
| 云端数据 | Run 78 条：validation 72（off/v1/v2 各 24）+ online 6；状态 RECOVERED 51、FAILED 18、SAFE_STOPPED 3、INCOMPLETE 5、IN_PROGRESS 1（残留）；validation 事件 76 条 |
| 测试 | 契约 11 例、后端 6 例、e2e 2 例、前端 6 例；`py -m pytest test -q` 全量 145 passed |
| 文档 | 契约、汇总、走查、交付骨架、数据请求单、学习计划均已入库 |
| 阻塞 | ROS 2 无环境；B 的 24 场景汇总未到 |

## 3. 交付目标（对应验收标准）

| 验收标准 | C 侧要提供 |
|---|---|
| 1 新人可复现基准卡滞 | 走查记录 + 一键演示脚本（已完成） |
| 2 同场景三策略 + `run_id` + 原始记录 | 三策略 Run 均入库并可导出（**当前缺 off/v1**） |
| 3 可达/不可达案例 | 决策与可达性字段可查询、可导出（机制已具备） |
| 4 样本数/分布/失败案例/数据位置 | 入库统计 + 失败清单 + 轨迹哈希清单（**待 B 数据**） |
| 5 演示故障、决策、恢复/停止及结果 | 录屏（**待录**） |
| 6 性能结论标注仿真条件 | 报告骨架已含条件声明（**待填数**） |

## 4. 任务板

### 4.1 剩余正式任务

| 编号 | 任务 | 输入 | 输出 | 验收 | 优先级 |
|---|---|---|---|---|---|
| C-02 | 补验 ROS 2/Gazebo 链路 | 有 ROS 2 的机器 | 对照 Run + 结论 | 能产出 `plant=ros2-gazebo` 的 Run 或书面「未验证」 | 低（阻塞） |
| C-16 | 演示录屏 | 分镜（`v2-delivery-outline.md`） | 3–5 分钟视频 | 覆盖故障→决策→页面→导出 | 中 |
| C-17 | 报告/PPT 定稿 | B 的 24 场景汇总（已到位） | 报告与 PPT | 每个数字回指 `run_id` | 高（报告已定稿；PPT 待生成） |

### 4.2 证据缺口（审查发现，建议并入任务板）

| 编号 | 问题 | 当前证据 | 动作 | 验收 |
|---|---|---|---|---|
| G-1 | ✅ 已完成：PR #2 已开（见 4.4） | `origin/develop-C = 6de3722`，已合并 `origin/develop` 对齐基线 | 开 PR 并跟进 CI | PR #2 含全部提交 |
| G-2 | ✅ 已补齐：72 条 validation Run 入库 | 见 4.4 | — | 72 条全部可查 |
| G-3 | ✅ 已完成三方核对 | 见 4.4 | — | 72/72 一致 |
| G-4 | ✅ 已完成：曲线取数口径写入契约 §8.1 | 见 4.4 | — | `docs/v2-experiment-contract.md` §8.1 |
| G-5 | ✅ 已完成：三策略对照结论（见 4.4） | 见 4.4；另发现 seed/onset 混淆，已提请 B 确认 | — | `docs/v2-strategy-comparison.md` |
| G-6 | ✅ 已完成：系统指标分布（见 4.4） | 见 4.4；网络丢包与墙钟抖动口径边界已注明 | — | `docs/v2-system-metrics.md` |
| G-7 | ✅ 已完成：详情页与导出组件测试 | 见 4.4 | — | 用例可回归 |
| G-8 | ✅ 已修复：末尾补换行 | 见 4.4 | — | diff 干净 |
| G-9 | ✅ 已完成：新增 split 过滤区分正式/演示 | 见 4.4 | — | 页面可按 split 筛选 |
| G-10 | ✅ 已完成：GitHub Actions 三端 CI | `.github/workflows/ci.yml`（见 4.4） | push / PR 自动运行 | backend / edge / frontend 三 job 全绿 |

优先级：**P0 = G-1、G-2、G-3**；P1 = G-4、G-5、C-17 准备；P2 = G-6、G-7、G-8、G-9、C-16、C-02。

### 4.3 已完成（不再跟踪）

C-01 Docker 链路、C-03 MQTT、C-04 `run_id` 贯通、C-05 事件贯通、C-06 存储、C-07 页面展示/导出、C-08 契约、C-09 运行配置、C-10 端到端测试、C-11 团队材料、C-12 复现走查、C-13 交付骨架、C-14 数字复核清单、C-15 数据请求单。

### 4.4 执行记录（2026-11-26 / 11-28）

| 编号 | 结果 | 证据 |
|---|---|---|
| G-2 | ✅ 完成 | 72 条 validation Run 全部入库；off/v1/v2 各 24；曲线 72/72 均 800 点；重复导入 0 失败 |
| G-3 | ✅ 完成 | `manifest ↔ DB ↔ trace.sha256` 全量比对：72/72 一致，缺失 0、哈希不符 0 |
| G-4 | ✅ 完成 | 曲线取数口径写入契约 §8.1：窗 = `[started_at, +duration_s]`、limit 默认 800/上限 2000、downsample 分桶语义；实测 validation Run 默认 800 点 span 8s，`limit=200` 截断为 200 点 2s。说明实时/中断 Run 点数<800 为预期行为 |
| G-5 | ✅ 完成 | 三策略对照：恢复率 off 45.8% → v1 79.2% → v2 87.5%；云端 51/18/3 与本地一致。**另发现 `fault_onset_s` 与 `seed` 完全混淆，已在 `docs/v2-strategy-comparison.md` §0 与请求单 §6 标注，请 B 确认** |
| G-6 | ✅ 完成 | 新增 `analyze_metrics.py` 汇总 72 条原始 trace（57,600 帧）：仿真控制周期 p50/p95/max 均 10ms，`step` 缺帧 0（0.0000%），72/72 Run 全程有界；报告含峰值速度/力矩与末 1 秒速度 RMS 的 p50/p95/max。明确轨迹缺帧≠MQTT 网络丢包、仿真周期≠墙钟调度 |
| C-17 | ✅ 报告定稿 | B 24 场景汇总已到位（`member-b-validation-frozen-r1.json`），与 C 侧 G-5 复现数字一致。生成 `docs/v2-final-report.md`（10 节填实）：恢复率 off 45.8%→v1 79.2%→v2 87.5%、v2 恢复耗时 p50 1.11s、3 例 J0 STOP 逐 run_id 列出、系统指标引自 G-6。交付骨架 §2/§4 状态同步更新。PPT 仍待生成 |
| G-1 | ✅ 完成 | 推送 develop-C（ae7d916→6de3722）并核验远端 SHA 一致；开 PR 前发现 develop-C 落后 origin/develop 6 个提交（B 的 PR #1 等），先合并同步基线，解决 `config_manager.py` / `main.py` 两处冲突取并集，py_compile 与 14 例契约/配置测试通过，PR diff 无 B 文件删除。**PR #2 已开**：develop-C → develop，https://github.com/RUzzkim/Simulated-Platform/pull/2 |
| 修复 | 回放脚本 | 云端只订阅 `simulation/{id}/state`；遥测入库读 `timestamp`。脚本补 `timestamp` 字段并把默认主题改为 `/state` |
| G-8 | ✅ 完成 | `docs/database-schema.sql` 末尾补 CRLF 换行，无其它改动 |
| G-9 | ✅ 完成 | 列表接口与页面新增 `split` 过滤（对 `split_name` 大小写不敏感精确匹配）。实测：无过滤 78、`validation` 72、`online` 6、`ONLINE`/`Validation` 大小写等价、`unknown` 0、`split=validation&status=FAILED`=18。正式（72）与演示（6）可区分，未删数据 |
| G-7 | ✅ 完成 | 新增 `Experiments.spec.js` 组件测试（@vue/test-utils + jsdom，stub reka-ui Dialog/Select、mock api/router/toast）：详情并发拉取运行/事件/曲线、元数据渲染、事件按仿真时间升序；导出 JSON/CSV 的文件名与下载触发。前端 11 例全过（API 7 + 组件 4） |
| G-10 | ✅ 完成 | 新增 `.github/workflows/ci.yml`：backend（JDK 21 + `mvn -B test`）、edge（Python 3.12 + pytest，排除依赖真实 broker 的 `test_status_e2e` / `test_graceful_exit_e2e`）、frontend（Node 20 + `npm ci` + `vitest run`）三 job 并行，push `develop`/`develop-C` 与对 `develop` 的 PR 触发。本地复跑同命令：后端 8/8、边端 162 passed + 26 subtests、前端 11 passed；YAML 解析校验通过 |

剩余：C-17（报告已定稿，PPT 待生成）；外部：B 确认 seed/onset 混淆、C-02（ROS 2）、C-16（录屏）、G-1 CI/审阅跟进（PR #2 待合并）。

## 5. 阶段路线

| 阶段 | 日期 | 内容 | 出口条件 |
|---|---|---|---|
| 环境基线 | 11/26 | Docker/MQTT/边端/页面 | 已完成；ROS 2 按降级文档处理 |
| 接口冻结 | 11/27–11/28 | 契约 2.0.0、schema、夹具 | 已完成 |
| 数据面补齐 | 11/29–12/03 | G-2、G-3、G-5、G-9 | 72 条入库，off/v1/v2 齐全，核对报告出具 |
| 对照与集成 | 12/04–12/06 | 接入 B 汇总，G-4、G-6 | 数字可回指，口径写入契约 |
| 冻结交付 | 12/07–12/09 | C-17、C-16、全量复核 | 报告/PPT/录屏齐备，DoD 全绿 |

## 6. 依赖与风险

| 风险 | 影响 | 应对 |
|---|---|---|
| B 的汇总延迟到 12/04 后 | 报告数字无法填 | 先用演示 Run 打通呈现链路，数字到位后只替换数据源 |
| 无 ROS 2 环境 | C-02 无法验证 | 维持降级表述，报告第 9 章明确「未验证」 |
| 录屏需人工 | C-16 排队 | 分镜已定，按幕录制，允许分段剪辑 |
| Docker 引擎不稳定（曾出现服务停止） | 演示中断 | 走查文档已记录恢复步骤；演示前先跑一次空栈启动 |
| 演示数据混入正式批次 | 数字污染 | G-9 打标或清理，导出时按 `split` 过滤 |

## 7. 完成定义（DoD）

- [x] 提交已推送，PR #2 可见全部改动
- [ ] 72 条 validation Run 全部入库，schema 校验通过
- [ ] `manifest ↔ DB ↔ sha256` 三方核对 72/72
- [ ] off / v1 / v2 三策略各有可查 Run
- [ ] 曲线点数与时间窗口径写入契约
- [ ] 报告与 PPT 中每个数字可回指 `run_id`
- [ ] 演示录屏 3–5 分钟，含故障、决策、导出
- [ ] ROS 2 有环境则补验，无则维持「未验证」表述
- [ ] 测试全绿：pytest 全量、`npm test`、后端单测

## 8. 检查点

- 每日：3 行记录（昨天完成 / 今天计划 / 阻塞）
- 每周五：更新本文件的任务状态与 `docs/v2-summary.md` 待办段
- 阶段结束：按第 5 节出口条件自查，未达标不进入下一阶段

## 9. 关联文档

| 文档 | 用途 |
|---|---|
| `docs/v2-summary.md` | 工程汇总与验证证据 |
| `docs/v2-experiment-contract.md` | 契约 2.0.0 与口径 |
| `docs/member-c-onboarding-walkthrough.md` | 复现走查与卡点 |
| `docs/v2-delivery-outline.md` | 交付骨架与复核判据 |
| `docs/v2-data-request-to-b.md` | 对 B 的数据请求 |
| `docs/member-c-learning-plan.md` | 能力建设 |
