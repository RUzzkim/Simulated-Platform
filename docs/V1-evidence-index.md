# V1.0 佐证材料索引

> 一页看全 V1.0 的全部佐证:对到《项目书》的量化指标与附录佐证清单,给出文件路径。
> 更新:2026-09-30。所有性能数字均为**仿真环境**实测/复现结果,不外推为现场指标。

## 1. 计划书量化指标 → 佐证

| 项目书指标(§3.2/§1.4/§6.3) | 目标 | 实测 | 佐证文件 |
|---|---|---|---|
| 轨迹跟踪误差较传统控制降低 | ≥30% | **50.5%**(24 场景均值,22/24 组 NN 更优) | `edge/edge_node/test/reports/comparison_report.md`、`figures/fig_control_pd_vs_nn.png`、`fig_convergence.png` |
| 控制延迟 | <10ms | **<1ms**(峰值 0.5ms) | 同上报告 |
| 容错响应时间(立即型故障) | <20ms | **10ms**(单控制周期) | 同上报告 |
| 故障后(安全降级)完成率提升 | ≥40% | ON 62.5% vs OFF 0%,**+62.5pp** | `comparison_report.md`、`figures/fig_fault_ftc_on_off.png` |
| 加密前后吞吐量损耗 | <5% | 运行负载/真实链路 **<5%**(0%) | `docs/security/encryption-verification.md` |
| 加密防护对抗测试成功率 | >99% | **100%**(25000/25000) | 同上 |
| 48 组对比测试 | 完成 48 组 | **48 组**(控制 24 + 容错 24) | `comparison_report.md` + `comparison_data.json` |
| 液压臂静力矩/闭环校核 | — | 力矩上限、重力矩、固有频率、PID vs ANNC | `sim/hydraulic-arm/results/simulation_report.md` + fig1-5 |

## 2. 端边云闭环佐证

| 环节 | 佐证 |
|---|---|
| 端(仿真) | `sim/gazebo_arm/`(ROS2 端,RViz + Gazebo 物理骨架 + steel_yard 世界);验证见其 README「验证状态」;`edge/edge_node/test/reports/v2.3_test_report.md`(物理仿真器 111/111 用例) |
| 边(实时控制/容错) | `edge/edge_node/`;`v2.3_test_report.md` §6-§15(容错闭环、信号滤波、故障上云) |
| 云(管理平台) | `backend/`+`frontend/`(9 页);已上线 ECS 106.15.43.100 |
| 端→边→云 mTLS 全链路 | `sim/gazebo_arm/README.md`「阶段3」(Docker 实测遥测入库、前端显示、下行 MOVE_JOINT 收敛) |

## 3. 对到项目书附录「佐证材料清单」8 项

| 附录项 | 我们有什么 | 状态 |
|---|---|---|
| 1 项目系统架构图 | `README.md` 三层表 + `docs/cloud-architecture.md` | ✅(文档;可再补一张示意图) |
| 2 软件平台设计文档 | `README.md`、`docs/cloud-architecture.md`、`dev-plan.md`、`rest-api.md`、`mqtt-contract.md`、`database-schema.sql` | ✅ |
| 3 仿真环境运行截图 | 前端页面、RViz/Gazebo 现场 | ⚠️ 需补统一截图集(见下待办) |
| 4 功能测试记录 | `v2.3_test_report.md`、`comparison_report.md`+3图、`encryption-verification.md`、`hydraulic-arm/results/` | ✅ |
| 5 项目研发过程材料 | 各报告含日期;git 打 tag 后即研发历史 | ⚠️ 待 git 初始化 |
| 6 团队成员分工说明 | 见项目书第七章 | ✅(非技术) |
| 7 指导教师指导材料 | 线下材料 | — 非技术 |
| 8 知识产权规划材料 | 见项目书 §8.4 | ✅(非技术) |

## 4. 佐证文件清单(路径)

```
README.md                                           三层总览 + 目录
docs/security/encryption-verification.md            加密验证报告(+ benchmark 脚本)
docs/security/encryption_benchmark.py / transport_benchmark.py
edge/edge_node/test/reports/comparison_report.md    48 组对比报告
edge/edge_node/test/reports/comparison_data.json    对比原始数据
edge/edge_node/test/reports/figures/                fig_control_pd_vs_nn / fig_convergence / fig_fault_ftc_on_off .png
edge/edge_node/test/reports/v2.3_test_report.md     物理仿真器 111/111 用例
edge/edge_node/test/benchmarks/                     对比测试台源码(可复现)
sim/hydraulic-arm/results/simulation_report.md      液压臂孪生报告 + fig1-5
sim/hydraulic-arm/results/wear_dataset/             执行器磨损数据集
sim/gazebo_arm/README.md                            仿真端验证状态
```

## 5. 尚缺 / 待补(诚实)

- **仿真环境运行截图集**(附录第 3 项):前端各页 + RViz/Gazebo 现场,建议统一截一组放 `docs/screenshots/`。
- **git 版本历史**(附录第 5 项):`git init` + 打 `v1.0.0` tag 后即形成研发历史。
- **架构示意图**(附录第 1 项):目前是文字/目录树,可再出一张端边云数据流图。
