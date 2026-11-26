# 成员 B · 8.5 与 10.0 N·m 阈值配对复核

实验日期为 2026-11-25。逐次运行、九个源码与配置 SHA-256 见 [8.5 N·m 结果](member-b-validation-threshold-paired-r1-8p5.json) 和 [10.0 N·m 结果](member-b-validation-threshold-paired-r1-10p0.json)。压缩轨迹位于两个 JSON 的 meta.raw_directory 指定目录，按 run_id 对应。

## 实验设置

沿用已有 validation 的 24 个单关节卡滞场景，覆盖 J0–J3、三个注入时刻和两组任务目标。为每个故障场景增加一条目标、负载和轨迹一致但不注入卡滞的对照。两组均使用 12.5 N·m 合成卡滞读数、零传感器噪声、edge_config.yaml 在线信号滤波，以及相同的仿真配置。分别测试 8.5 与 10.0 N·m 检测阈值，每种条件运行容错关闭、V1 和 V2，共 144 次/阈值，合计 288 次，每次记录 800 帧。

| 阈值 | 策略 | 故障检出 | 无故障误报 | 平均确认延迟 | 轨迹恢复 | 安全停稳 |
|---:|---|---:|---:|---:|---:|---:|
| 8.5 N·m | 容错关闭 | — | — | — | 11/24 | 0/24 |
| 8.5 N·m | V1 | 24/24 | 0/24 | 251.667 ms | 19/24 | 0/24 |
| 8.5 N·m | V2 | 24/24 | 0/24 | 251.667 ms | 21/24 | 3/24 |
| 10.0 N·m | 容错关闭 | — | — | — | 11/24 | 0/24 |
| 10.0 N·m | V1 | 24/24 | 0/24 | 251.667 ms | 19/24 | 0/24 |
| 10.0 N·m | V2 | 24/24 | 0/24 | 251.667 ms | 21/24 | 3/24 |

## 结果解读

在本轮 12.5 N·m 读数下，8.5 与 10.0 N·m 阈值的各策略逐场景结果完全一致。两者均检出全部 24 个卡滞场景，V1、V2 在各自 24 条无故障对照中均未出现误报，确认延迟和恢复、停稳评分也相同。由于输入读数高于两个阈值，本轮没有显示降低阈值带来额外检测收益，也未观察到这 24 条对照中的误报增加。

每档阈值仅包含 24 条匹配无故障轨迹，且轨迹来自已使用的 validation 场景。因此零误报只描述这组仿真条件，不能外推为一般误报率，也不构成独立盲测。该结果不覆盖阈值附近读数、传感器漂移、变化负载或通信故障。默认阈值保持 10.0 N·m，8.5 N·m 仍作为候选值记录。

## 复现

在仓库根目录分别运行以下命令。两组原始轨迹输出目录已被 Git 忽略，JSON 摘要和本报告纳入版本管理。

~~~powershell
py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --lock-torque-threshold 8.5 --online-signal-filter --include-no-fault-controls --output-dir edge/edge_node/test/reports/task_recovery/member-b-validation-threshold-paired-r1-8p5 --json docs/member-b-validation-threshold-paired-r1-8p5.json
py edge/edge_node/test/benchmarks/run_task_recovery.py --split validation --lock-torque-threshold 10.0 --online-signal-filter --include-no-fault-controls --output-dir edge/edge_node/test/reports/task_recovery/member-b-validation-threshold-paired-r1-10p0 --json docs/member-b-validation-threshold-paired-r1-10p0.json
py -m pytest -q edge/edge_node/test
~~~
