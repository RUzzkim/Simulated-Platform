# 成员 B · 卡滞后目标可达性验证

本报告核查 J0 卡滞后目标能否在末端位置容差内到达。判据只覆盖末端位置，不评价姿态。

## 锁定约束下可达

场景 `VALIDATION-LOCK-J0#s1T1` 在 0.40 s 注入卡滞。V2 轨迹于 8.00 s 提供一组关节状态，J0 固定在 0.028222729 rad。正运动学末端误差为 0.016335 m，小于 0.020 m 见证容差，因此该关节向量证明目标在锁定约束下可达。闭环恢复耗时 2.86 s，最终误差 0.016335 m。

## 锁定约束下不可达

场景 `VALIDATION-LOCK-J0#s1T2` 在 0.40 s 注入卡滞，锁定角为 -0.052781084 rad。固定 J0 后，DH 前五个坐标系的原点位于由基座锁定角确定的径向平面内。第 5 行轴向偏距沿平面内轴线，仅第 6 行轴向偏距贡献平面外位移，上限为 0.100 m。目标的切向投影为 -0.343766 m，末端位置误差至少为投影绝对值减去这一上限，即 0.243766 m，大于 0.050 m 评分容差。V2 输出 `STOP`，原因为 `NO_FEASIBLE_PLAN`，并在 0.19 s 达到停稳评分。

## 三策略配对复跑

| 场景 | 策略 | 检测延迟 | 恢复 | 停稳 | 最终末端误差 | 峰值关节速度 |
|---|---|---:|---:|---:|---:|---:|
| VALIDATION-LOCK-J0#s1T1 | off | 未检出 | 否 | 否 | 0.183481 m | 0.517834 rad/s |
| VALIDATION-LOCK-J0#s1T1 | v1 | 240.0 ms | 否 | 否 | 0.171736 m | 0.468106 rad/s |
| VALIDATION-LOCK-J0#s1T1 | v2 | 240.0 ms | 是 | 否 | 0.016335 m | 0.999968 rad/s |
| VALIDATION-LOCK-J0#s1T2 | off | 未检出 | 否 | 否 | 0.275031 m | 0.446352 rad/s |
| VALIDATION-LOCK-J0#s1T2 | v1 | 240.0 ms | 否 | 否 | 0.271172 m | 0.874616 rad/s |
| VALIDATION-LOCK-J0#s1T2 | v2 | 240.0 ms | 否 | 是 | 0.325215 m | 0.40983 rad/s |

两种故障目标各有同轨迹无故障对照，六条关闭容错、V1、V2 无故障运行均无误报。无故障对照 run_id 已记录在证书 JSON。使用默认 10.0 N·m 检测阈值、合成卡滞读数 12.5 N·m、100 Hz 控制周期。

## 适用范围

可达结论是正运动学存在性证明。不可达结论是针对仓库通用 6R DH 模型和记录锁定角的几何下界。两个目标来自此前已用过的 validation 场景，本次只复核可达性和可复现性，不构成独立盲测或实体机械臂结论。不可达证明使用末端位置判据，没有评价末端姿态。

复现命令：

~~~powershell
py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --scenario 'VALIDATION-LOCK-J0#s1T1' 'VALIDATION-LOCK-J0#s1T2' --include-no-fault-controls --output-dir edge/edge_node/test/reports/task_recovery/member-b-reachability-check-r1 --json edge/edge_node/test/reports/task_recovery/member-b-reachability-check-r1/summary.json
py edge/edge_node/test/benchmarks/validate_reachability.py --summary edge/edge_node/test/reports/task_recovery/member-b-reachability-check-r1/summary.json
py -m pytest -q edge/edge_node/test/test_reachability_certificate.py
~~~

本轮汇总 JSON SHA-256：`e9c345a932c3d55aea65c815278a1eb6c92eb4c7ca0ec5390d6fdcd27667198d`。可达见证与不可达下界使用该哈希对应的复跑数据。

逐次 run_id、可达关节见证、几何误差下界和 SHA-256 见相邻 JSON。
