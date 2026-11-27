# 成员 B · J0、J2–J4 含噪声卡滞恢复复核 r1

日期为 2026-11-26。实验在仓库通用六轴标准 DH Python plant 上运行，覆盖 J0 基座回转、J2 肩、J3 肘和 J4 腕四个单关节卡滞位置。算法关节索引从 0 开始，分别对应模型 joint_1 至 joint_4。这里以实验方案中的 J0–J4 标注故障部位，其中模型 joint_2 对应机械臂肩关节 J2，模型 joint_3 对应肘关节 J3，模型 joint_4 对应腕关节 J4。

## 实验设计与复核范围

冻结 validation 集有 24 个故障场景，每个关节覆盖两个点到点目标和三个注入时刻。每个场景使用噪声种子 42、43、44，比较容错关闭、V1、V2，并为每种策略配对一条无故障对照。共 216 次故障运行和 216 次无故障对照。采样率为 100 Hz，启用在线信号滤波，检测阈值为 10.0 N·m，合成卡滞读数为 12.5 N·m，故障关节读数叠加 σ=1.5 N·m 高斯噪声。

噪声只作用于故障关节的传感器读数，不改变仿真对象的物理状态。每个工况的三个噪声种子是固定目标上的重复运行，不是三个独立目标。validation 场景此前已用于实验，因此本轮不是独立盲测。

恢复评分要求故障期间末端位置误差不超过 50 mm，持续至少 0.25 s 并保持至运行结束。停稳评分要求 STOP 后所有关节速度不超过 0.05 rad/s，连续保持同一时长，并在 2.0 s 限时内达标。

## 全局结果

| 策略 | 恢复评分 | 安全停稳 | 故障检出 | 配对无故障误报（V1/V2） | 平均检出延迟 |
|---|---:|---:|---:|---:|---:|
| off | 33/72 | 0/72 | 不适用 | 不适用 | — |
| v1 | 57/72 | 0/72 | 72/72 | 0/72 | 252.1 ms |
| v2 | 63/72 | 9/72 | 72/72 | 0/72 | 252.1 ms |

## 按关节统计

| 故障关节 | 策略 | 检出 | 恢复评分通过 | 安全停稳通过 | 平均检出延迟 | 平均恢复用时 | 配对无故障误报 |
|---|---|---:|---:|---:|---:|---:|---:|
| J0 基座回转轴（索引 0） | off | 不适用 | 3/18 | 0/18 | — | 0.260 s | 不适用 |
| J0 基座回转轴（索引 0） | v1 | 18/18 | 3/18 | 0/18 | 253.9 ms | 0.260 s | 0/18 |
| J0 基座回转轴（索引 0） | v2 | 18/18 | 9/18 | 9/18 | 253.9 ms | 1.710 s | 0/18 |
| J2 肩关节（索引 1） | off | 不适用 | 6/18 | 0/18 | — | 0.325 s | 不适用 |
| J2 肩关节（索引 1） | v1 | 18/18 | 18/18 | 0/18 | 251.7 ms | 1.028 s | 0/18 |
| J2 肩关节（索引 1） | v2 | 18/18 | 18/18 | 0/18 | 251.7 ms | 1.110 s | 0/18 |
| J3 肘关节（索引 2） | off | 不适用 | 6/18 | 0/18 | — | 0.330 s | 不适用 |
| J3 肘关节（索引 2） | v1 | 18/18 | 18/18 | 0/18 | 251.7 ms | 0.940 s | 0/18 |
| J3 肘关节（索引 2） | v2 | 18/18 | 18/18 | 0/18 | 251.7 ms | 0.870 s | 0/18 |
| J4 腕关节（索引 3） | off | 不适用 | 18/18 | 0/18 | — | 0.717 s | 不适用 |
| J4 腕关节（索引 3） | v1 | 18/18 | 18/18 | 0/18 | 251.1 ms | 0.985 s | 0/18 |
| J4 腕关节（索引 3） | v2 | 18/18 | 18/18 | 0/18 | 251.1 ms | 0.877 s | 0/18 |

V2 在肩关节 J2、肘关节 J3、腕关节 J4（遥测 jointIndex 1–3）三个关节组各 18/18 达到恢复评分。J0 基座原始恢复评分为 9/18、停稳 9/18。以下将 J0 的 18 次运行按锁定角和几何可达性分类，并与规划器最佳搜索误差逐项对照。

## J0 锁定角下的几何复核

| J0 工况 | 实测锁定角 | 几何误差下界 | 规划器动作 / 原因 | 最佳搜索误差 | V2 结果 | 可达性证据 |
|---|---:|---:|---|---:|---:|---|
| `VALIDATION-LOCK-J0#s1T1` | 0.028222729 rad | 0.000 mm | `RECOVER / TARGET_REACHED` | 16.366 mm | 恢复 3/3，停稳 0/3 | 闭环实证可达 |
| `VALIDATION-LOCK-J0#s1T2` | -0.052781084 rad | 243.766 mm | `STOP / NO_FEASIBLE_PLAN` | 243.766 mm | 恢复 0/3，停稳 3/3 | 证明不可达 |
| `VALIDATION-LOCK-J0#s2T1` | 0.161163937 rad | 0.000 mm | `RECOVER / TARGET_REACHED` | 10.893 mm | 恢复 3/3，停稳 0/3 | 闭环实证可达 |
| `VALIDATION-LOCK-J0#s2T2` | -0.259676353 rad | 158.250 mm | `STOP / NO_FEASIBLE_PLAN` | 158.250 mm | 恢复 0/3，停稳 3/3 | 证明不可达 |
| `VALIDATION-LOCK-J0#s3T1` | 0.300103753 rad | 0.000 mm | `RECOVER / TARGET_REACHED` | 17.366 mm | 恢复 3/3，停稳 0/3 | 闭环实证可达 |
| `VALIDATION-LOCK-J0#s3T2` | -0.488513650 rad | 51.001 mm | `STOP / NO_FEASIBLE_PLAN` | 51.001 mm | 恢复 0/3，停稳 3/3 | 证明不可达 |

几何误差下界按目标位置到锁定 J0 所限定径向平面的切向距离，减去模型最后一个 DH 轴向偏距 0.100 m 计算。前一个 0.100 m 偏距沿径向平面内轴线，不贡献平面外位移。只有误差下界严格大于 0.050 m 恢复评分容差时，才认定该目标在评分意义下不可达。规划器在故障确认帧复跑，动作、原因均与记录一致。可达目标 T1 的三组注入时刻共 9 次 V2 运行全部通过恢复评分，三个不可达目标 T2 工况共 9 次 V2 运行均安全停稳。表中 s3T2 的误差下界为 51.001 mm，仅比 50 mm 评分容差高 1.001 mm，结论对通用模型尺寸误差敏感。按无条件计分的 J0 恢复率仍是 9/18。

## 代表性回放轨迹

| 回放内容 | run_id | 轨迹 |
|---|---|---|
| J0 可恢复目标 | `857c30214ff64bc789ba8b2d5b9a587f` | [CSV.gz](experiments/member-b-all-joints-noise-repeat-r1/traces/857c30214ff64bc789ba8b2d5b9a587f.csv.gz) |
| J0 锁定后几何不可达目标 | `e1df4542c1894e059f641c78e1228bd2` | [CSV.gz](experiments/member-b-all-joints-noise-repeat-r1/traces/e1df4542c1894e059f641c78e1228bd2.csv.gz) |
| J0 锁定后略超评分容差的目标 | `ecfb9e9b1443456da185e890acae3a5c` | [CSV.gz](experiments/member-b-all-joints-noise-repeat-r1/traces/ecfb9e9b1443456da185e890acae3a5c.csv.gz) |
| 肩关节 J2 卡滞恢复 | `f7a0657837df41bcac4942e28669969d` | [CSV.gz](experiments/member-b-all-joints-noise-repeat-r1/traces/f7a0657837df41bcac4942e28669969d.csv.gz) |
| 肘关节 J3 卡滞恢复 | `52d1733263b94e0d9374b7ef12da5206` | [CSV.gz](experiments/member-b-all-joints-noise-repeat-r1/traces/52d1733263b94e0d9374b7ef12da5206.csv.gz) |
| 腕关节 J4 卡滞恢复 | `ea6fc0d47b62433fbbca310cd52c8fc3` | [CSV.gz](experiments/member-b-all-joints-noise-repeat-r1/traces/ea6fc0d47b62433fbbca310cd52c8fc3.csv.gz) |

每条轨迹含 800 个控制周期的关节位置、速度、力矩、状态滤波读数、动作和故障标记。轨迹内容及 SHA-256 写入机器可读清单。

## 重跑与边界

机器可读清单列出全部 432 次运行的 run_id、评分结果、原始轨迹 SHA-256 和源码 SHA-256。以下命令先重跑三个策略和配对对照，生成本地原始轨迹，然后由汇总脚本复核源码版本、J0 锁定角下界、逐次轨迹、回放样例和本报告。原始 432 份 CSV.gz 轨迹保留在 Git 忽略的 reports 目录。

~~~powershell
py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --include-no-fault-controls --online-signal-filter --lock-reaction-torques 12.5 --sensor-torque-noise-sigmas 1.5 --sensor-noise-seeds 42 43 44 --output-dir edge/edge_node/test/reports/task_recovery/member-b-all-joints-noise-repeat-r1 --json edge/edge_node/test/reports/task_recovery/member-b-all-joints-noise-repeat-r1/summary.json
py edge/edge_node/test/benchmarks/summarize_all_joints_repeat.py
~~~

完整逐次清单：[manifest.json](experiments/member-b-all-joints-noise-repeat-r1/manifest.json)。运行汇总 JSON SHA-256 为 `d51065ff8507708f56cf8d84dce0f8021ed92d54cd4237979165eb04d9dec22a`。

本轮只验证通用 DH 仿真模型，没有验证具体品牌机械臂、实体传感器或实体执行器。仅覆盖末端位置，没有覆盖末端姿态或抓取成功率。当前结果没有新增 Docker、ROS 2、MQTT 在线运行数据。J0 几何下界只适用于记录中的 DH 参数、目标和锁定角。
