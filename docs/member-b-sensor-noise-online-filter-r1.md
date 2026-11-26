# 成员 B · 在线信号滤波下力矩噪声敏感性探索

实验日期为 2026-11-25，逐次结果与源码 SHA-256 见 [实验数据](member-b-sensor-noise-online-filter-r1.json)。压缩轨迹保存在本地忽略目录 `edge/edge_node/test/reports/task_recovery/member-b-sensor-noise-online-filter-r1/`，按 JSON 中的 `meta.raw_directory` 和 `run_id` 对应。

## 实验设置

上一轮探索将合成传感器读数直接送入故障检测器。在线边缘流程会先运行 `RobotSignalFilter`，再将滤波状态送入检测和容错控制。本轮在任务恢复基准中启用 `--online-signal-filter`，读取 `edge_config.yaml` 的滤波参数，按 MAD 离群点处理、中值和 EMA 的顺序处理位置、速度与力矩。滤波后的状态用于检测器与控制器，原始物理轨迹和传感器读数仍分别记录。

沿用探索集 J0–J3 各两个场景，故障力矩读数 9、11、13 N·m，力矩噪声标准差 0、1.5、3 N·m，随机种子 42、43。每种条件增加无故障对照，容错关闭、V1、V2 各运行一次，共 288 个场景条件、864 次仿真。每次仿真 8 秒、100 Hz。

| 合成故障力矩读数 | 噪声标准差 σ | V1/V2 检出 | 平均确认延迟 | 无故障误报 | V2 恢复 | V2 安全停稳 |
|---:|---:|---:|---:|---:|---:|---:|
| 9 N·m | 0 N·m | 0/16 | — | 0/16 | 4/16 | 0/16 |
| 9 N·m | 1.5 N·m | 1/16 | 4.510 s | 0/16 | 4/16 | 0/16 |
| 9 N·m | 3 N·m | 15/16 | 1.865 s | 0/16 | 13/16 | 2/16 |
| 11 N·m | 0 N·m | 16/16 | 0.254 s | 0/16 | 14/16 | 2/16 |
| 11 N·m | 1.5 N·m | 16/16 | 0.258 s | 0/16 | 14/16 | 2/16 |
| 11 N·m | 3 N·m | 16/16 | 0.265 s | 0/16 | 14/16 | 2/16 |
| 13 N·m | 0 N·m | 16/16 | 0.251 s | 0/16 | 14/16 | 2/16 |
| 13 N·m | 1.5 N·m | 16/16 | 0.253 s | 0/16 | 14/16 | 2/16 |
| 13 N·m | 3 N·m | 16/16 | 0.252 s | 0/16 | 14/16 | 2/16 |

V1、V2 共用检测器，整体均为 112/144 检出、32 次漏检，平均确认延迟 509 ms，中位数 250 ms。144 次无故障对照中两者均为 0 次误报。V1 的恢复评分为 81/144，V2 为 105/144，另有 14/144 次 V2 运行通过安全停稳评分。恢复评分表示仿真轨迹结果，不能单独证明是容错决策促成。

低于检测阈值的 9 N·m 条件仍不稳定。σ=0 时没有检出，σ=1.5 时仅 1/16 检出且平均延迟 4.51 秒，σ=3 时 15/16 检出但平均延迟 1.87 秒。这些迟发检出反映噪声读数偶尔越过固定阈值，不能据此认为噪声改善了检测能力。11 与 13 N·m 条件均 16/16 检出，确认延迟约 251–265 ms。

## 适用范围

本轮使用合成高斯读数噪声、两个随机种子和八个已使用过的探索场景，不是实体传感器标定，也不是独立盲测。与上一轮未滤波实验相比，本轮滤波状态还会进入容错控制器并改变闭环轨迹，因此计数差异不能单独归因于检测器滤波。结果只描述当前配置、噪声设定和仿真对象下的表现。

在仓库根目录复现本轮矩阵：

~~~powershell
py edge/edge_node/test/benchmarks/run_task_recovery.py --split exploratory --scenario 'EXPLORATORY-LOCK-J0#s1T1' 'EXPLORATORY-LOCK-J0#s3T2' 'EXPLORATORY-LOCK-J1#s1T1' 'EXPLORATORY-LOCK-J1#s3T2' 'EXPLORATORY-LOCK-J2#s1T1' 'EXPLORATORY-LOCK-J2#s3T2' 'EXPLORATORY-LOCK-J3#s1T1' 'EXPLORATORY-LOCK-J3#s3T2' --lock-reaction-torques 9 11 13 --sensor-torque-noise-sigmas 0 1.5 3 --sensor-noise-seeds 42 43 --include-no-fault-controls --online-signal-filter --output-dir edge/edge_node/test/reports/task_recovery/member-b-sensor-noise-online-filter-r1 --json docs/member-b-sensor-noise-online-filter-r1.json
py -m pytest -q edge/edge_node/test
~~~
