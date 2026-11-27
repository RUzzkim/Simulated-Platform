# 成员 B · 重复工况与随机噪声复核 r1

日期为 2026-11-26。本轮使用仓库六轴标准 DH Python plant，对冻结验证集中的 J2 肩关节恢复目标及 J0 基座回转轴可达/不可达目标进行重复复核。J2 对应模型 `joint_2` 和遥测索引 1，J0 对应模型 `joint_1` 和遥测索引 0。每个目标使用噪声种子 42、43、44，并运行容错关闭、V1、V2 三种策略，同时加入同轨迹无故障对照。

## 固定配置

| 配置 | 值 |
|---|---:|
| 采样频率 | 100 Hz |
| 卡滞检测阈值 | 10.0 N·m |
| 卡滞合成力矩读数 | 12.5 N·m |
| 故障关节力矩读数噪声 | 高斯噪声 σ = 1.5 N·m |
| 在线信号滤波 | 启用，复用边缘端配置 |
| 恢复评分 | 末端位置误差 ≤ 50 mm，连续保持至少 0.25 s |
| 停稳评分 | 全关节速度 ≤ 0.05 rad/s，持续保持至少 0.25 s，且从 STOP 起 2 s 内达标 |

噪声只加到故障关节的力矩传感器读数，不改变 plant 的物理力矩、运动学或动力学。本轮复用既有 validation 场景和模型，不是独立盲测。

## 结果

| 模型关节与工况 | V2 故障检出 | V2 恢复 | V2 安全停稳 | 对应无故障对照误报 | 平均确认延迟 |
|---|---:|---:|---:|---:|---:|
| J2 肩关节，可达目标 | 3/3 | 3/3 | 0/3 | 0/6 | 250.0 ms |
| J2 肩关节，第二目标 | 3/3 | 3/3 | 0/3 | 0/6 | 250.0 ms |
| J0 基座回转轴（`joint_1`），可达目标 | 3/3 | 3/3 | 0/3 | 0/6 | 250.0 ms |
| J0 基座回转轴（`joint_1`），几何不可达目标 | 3/3 | 0/3 | 3/3 | 0/6 | 253.3 ms |

物理模型 J2（边缘遥测 `jointIndex=1`）的两个冻结目标在 V1、V2 下均能恢复，重复结果未显示 V2 相对 V1 的恢复成功率优势。这组用于复核 J2 故障定位、噪声条件下的恢复重复性和可视化素材。

J2 第二目标在本轮模型闭环评分中恢复成功。本报告没有为该目标单独构造几何可达性证明；几何不可达下界只针对下述 J1 基座轴案例。

物理模型 J0 基座回转轴目标 `VALIDATION-LOCK-J0#s1T1` 在三个噪声种子下均由 V2 恢复，平均恢复时间为 2.87 s。目标 `VALIDATION-LOCK-J0#s1T2` 在三个种子下均由 V2 停稳，平均 STOP 至达标时间为 0.16 s。沿用记录锁定角与标准 DH 几何计算的末端位置误差下界为 243.766 mm，高于 50 mm 评分容差。V1 在该不可达目标的三次复跑中均未达到停稳评分。

两个目标共 12 条故障运行。每个目标、每个种子都为 off、V1、V2 分别运行同轨迹无故障对照，因此 V1 与 V2 各有 12 条无故障对照，均未记录误报。每组内更换的是力矩读数噪声种子，机械臂目标与故障注入参数保持固定，三次复跑不能解读成三个独立目标或实体设备样本。

## 可回放文件与复现

附带四条种子 42 的 V2 逐帧轨迹，包含 `run_id`、场景、参考目标、六轴位置/速度/力矩、故障字段、动作及原因，供 A 导入回放。JSON 清单列出 72 次运行的 run_id、逐次评分、原始压缩轨迹 SHA-256、源码 SHA-256 和两份基准汇总文件 SHA-256。全部 72 条原始轨迹都保留在本地忽略的 reports 目录，文档内附带其中四条供分享和回放。

| 回放案例 | run_id | 轨迹文件 |
|---|---|---|
| J2 肩关节，可达目标 | `076b5b0e3eb649ddbc65f35eae69f3af` | [CSV.gz](experiments/member-b-repeat-validation-r1/traces/076b5b0e3eb649ddbc65f35eae69f3af.csv.gz) |
| J2 肩关节，第二目标 | `9c71c85bfab8490fa6ecc813f1a9162b` | [CSV.gz](experiments/member-b-repeat-validation-r1/traces/9c71c85bfab8490fa6ecc813f1a9162b.csv.gz) |
| J0 基座回转轴，可达目标 | `cd4b7e42e0b34272b2f66aa741250b15` | [CSV.gz](experiments/member-b-repeat-validation-r1/traces/cd4b7e42e0b34272b2f66aa741250b15.csv.gz) |
| J0 基座回转轴，几何不可达目标 | `9a88447d5f5b4eb8aa496087e1940f44` | [CSV.gz](experiments/member-b-repeat-validation-r1/traces/9a88447d5f5b4eb8aa496087e1940f44.csv.gz) |

~~~powershell
py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --scenario VALIDATION-LOCK-J1#s1T1 VALIDATION-LOCK-J1#s1T2 --include-no-fault-controls --online-signal-filter --sensor-torque-noise-sigmas 1.5 --sensor-noise-seeds 42 43 44 --output-dir edge/edge_node/test/reports/task_recovery/member-b-j2-noise-repeat-r1 --json edge/edge_node/test/reports/task_recovery/member-b-j2-noise-repeat-r1/summary.json
py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --scenario VALIDATION-LOCK-J0#s1T1 VALIDATION-LOCK-J0#s1T2 --include-no-fault-controls --online-signal-filter --sensor-torque-noise-sigmas 1.5 --sensor-noise-seeds 42 43 44 --output-dir edge/edge_node/test/reports/task_recovery/member-b-j0-reachability-repeat-r1 --json edge/edge_node/test/reports/task_recovery/member-b-j0-reachability-repeat-r1/summary.json
~~~

机器可读实验清单：[manifest.json](experiments/member-b-repeat-validation-r1/manifest.json)，SHA-256 为 `8f9c31ff6b9abb53bb44eb09d05a2c3e7ce809009b386bf4b2da6ba0417bf8bf`。

## 本轮边界

这轮是成员 B 的 Python plant 算法和实验验证，未执行 Docker 在线复跑。本机 Docker daemon 当前不可访问。四条随文档提供的轨迹来自离线模型，不是 MQTT 遥测；云端入库验证与在线命令/决策关联仍需在 Docker 恢复后和 C 联调。
