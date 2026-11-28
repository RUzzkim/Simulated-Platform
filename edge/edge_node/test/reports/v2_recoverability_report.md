# V2.0 单关节卡滞后任务可恢复性实验报告

- 实验批次：`official-validation-r1-20261126`
- 协议来源：GitHub `RUzzkim/Simulated-Platform`，分支 `develop`，提交 `a0a6b3b`
- 冻结文件：`docs/member-b-validation-frozen-r1.json`；检出文件 sha256 `093abe19…`，Git blob sha256 `028d8bad…`（Windows 检出为 CRLF）
- 复跑命令：`py -B test/benchmarks/run_task_recovery.py --split validation --output-dir test/reports/task_recovery/validation-repro-r1`
- 复跑工作树：`D:\Simulated-Platform-v2run-a0`（detached at a0a6b3b，未改动 develop-C）
- 本报告所有数字均由 `summary.json` 与 72 个原始 `*.csv.gz` 轨迹直接生成。

> **仿真条件**：Python 数值孪生 6R 机械臂，单机运行，不接 ROS 2/Gazebo/真实机械臂；100Hz、8s/次、validation 划分 24 场景 × off/v1/v2 = 72 次运行。validation 集在本轮运行前由远程仓库冻结，但不是盲测。

## 1. 冻结判据

- 末端位置容差 `0.05m`，需在故障期连续保持 `0.25s` 至运行结束。
- 安全停止：决策后 `2.0s` 内所有关节速度 ≤ `0.05rad/s`，并保持 `0.25s`。
- 全程安全边界：|q|≤π、关节速度 ≤ `1.96rad/s`、力矩 ≤ `50.0N·m。
- 故障关节故障期平均 |τ| 必须 < `15.0N·m`。
- 卡滞力矩读数 `[12.5]N·m`，检测阈值 `[10.0]N·m`。
- 恢复轨迹健康关节速度上限 `1.0rad/s`、加速度上限 `2.0rad/s²`。

## 2. 场景与随机种子

- 故障关节：J0/J1/J2/J3（基座回转、肩、肘、腕）。
- 故障时刻：0.4s / 0.8s / 1.2s（s1/s2/s3），持续到运行结束。
- 目标：T1 `[0.35,0.55,-0.30,0.20,-0.15,0.10]`，T2 `[-0.60,0.25,0.45,-0.20,0.30,-0.25]`。
- 随机种子：300/301/302（对应 s1/s2/s3）。被控对象确定性，本轮不使用随机数。

## 3. 三策略结果（validation，24 场景）

| 策略 | 恢复 | 安全停止 | 检出率 | 平均检出延迟(ms) | 平均恢复耗时(s) | 平均停止耗时(s) |
|---|---|---|---|---|---|---|
| off | 11/24 (45.8%) | 0/24 (0.0%) | - | - | 0.534 | - |
| v1 | 19/24 (79.2%) | 0/24 (0.0%) | 100.0% | 240.0 | 0.934 | - |
| v2 | 21/24 (87.5%) | 3/24 (12.5%) | 100.0% | 240.0 | 1.053 | 0.15 |

按故障关节拆分（v2）：

| 故障关节 | 场景数 | 恢复 | 安全停止 |
|---|---|---|---|
| J0 | 6 | 3 | 3 |
| J1 | 6 | 6 | 0 |
| J2 | 6 | 6 | 0 |
| J3 | 6 | 6 | 0 |

## 4. 逐次运行与 run_id

每个 run_id 对应 `data/official-validation-r1/<run_id>.csv.gz`，含 800 帧原始 q/qd/τ/指令/参考/传感器读数。

| run_id | 场景 | 策略 | 种子 | 检出(ms) | 决策(s) | 动作 | 结果 | 末端误差(m) | 故障关节峰值τ(N·m) |
|---|---|---|---|---|---|---|---|---|---|
| 354fc1b75c0e49d1961b78f83187fe42 | VALIDATION-LOCK-J0#s1T1 | off | 300 | - | - | - | FAILED | 0.183481 | 12.5 |
| c3e55531e6894a859f7ea9bae3a1acd9 | VALIDATION-LOCK-J0#s1T1 | v1 | 300 | 240.0 | - | - | FAILED | 0.171736 | 12.5 |
| e3529e787dd842be943f06eaa0087df8 | VALIDATION-LOCK-J0#s1T1 | v2 | 300 | 240.0 | 0.64 | RECOVER | RECOVERED | 0.016336 | 12.5 |
| 6086cb610b384bdb88c935a98e1f566b | VALIDATION-LOCK-J0#s1T2 | off | 300 | - | - | - | FAILED | 0.275031 | 12.5 |
| 450a4f87b36f4147becc0ef73c124757 | VALIDATION-LOCK-J0#s1T2 | v1 | 300 | 240.0 | - | - | FAILED | 0.271172 | 12.5 |
| e8d5d5e2a5e748ec92867b5f2ca6471f | VALIDATION-LOCK-J0#s1T2 | v2 | 300 | 240.0 | 0.64 | STOP | SAFE_STOPPED | 0.325215 | 12.5 |
| a6a2102d096943a8a97e04007eb293e9 | VALIDATION-LOCK-J0#s2T1 | off | 301 | - | - | - | FAILED | 0.107858 | 12.5 |
| f385806c80a14dc9ac039c510e191be5 | VALIDATION-LOCK-J0#s2T1 | v1 | 301 | 240.0 | - | - | FAILED | 0.10283 | 12.5 |
| d2d691e4511745c7b8276f640d471f36 | VALIDATION-LOCK-J0#s2T1 | v2 | 301 | 240.0 | 1.04 | RECOVER | RECOVERED | 0.010923 | 12.5 |
| c09bb66b494a4cf383fd1a36cda98921 | VALIDATION-LOCK-J0#s2T2 | off | 301 | - | - | - | FAILED | 0.173309 | 12.5 |
| aba3cc424f71413388f50e92f432322b | VALIDATION-LOCK-J0#s2T2 | v1 | 301 | 240.0 | - | - | FAILED | 0.174383 | 12.5 |
| d22d20c7ed61436ebda49c90747abd30 | VALIDATION-LOCK-J0#s2T2 | v2 | 301 | 240.0 | 1.04 | STOP | SAFE_STOPPED | 0.184359 | 12.5 |
| 332b7b3b8c1a46068f6fa0aafcc8d389 | VALIDATION-LOCK-J0#s3T1 | off | 302 | - | - | - | RECOVERED | 0.028492 | 12.5 |
| 9cd8fc2a310f4910865d6c0baaf78f34 | VALIDATION-LOCK-J0#s3T1 | v1 | 302 | 240.0 | - | - | RECOVERED | 0.027718 | 12.5 |
| d063d465a51b42d284732546dd49344b | VALIDATION-LOCK-J0#s3T1 | v2 | 302 | 240.0 | 1.44 | RECOVER | RECOVERED | 0.017399 | 12.5 |
| 3bdb590c366548bab829e03af85c6e47 | VALIDATION-LOCK-J0#s3T2 | off | 302 | - | - | - | FAILED | 0.057229 | 12.5 |
| 3eb62cf49c8f471ab5f9c3295cb13e87 | VALIDATION-LOCK-J0#s3T2 | v1 | 302 | 240.0 | - | - | FAILED | 0.057921 | 12.5 |
| 095634d912274a02b5eb4480233a91f8 | VALIDATION-LOCK-J0#s3T2 | v2 | 302 | 240.0 | 1.44 | STOP | SAFE_STOPPED | 0.058619 | 12.5 |
| d5dff7155d094f13a49b56946623f3e0 | VALIDATION-LOCK-J1#s1T1 | off | 300 | - | - | - | FAILED | 0.30541 | 12.5 |
| fa7dbc65d78a45118cffb44dd1fc7dd1 | VALIDATION-LOCK-J1#s1T1 | v1 | 300 | 240.0 | - | - | RECOVERED | 0.010953 | 12.5 |
| 15df49f21b3241049603c98d1a0baeae | VALIDATION-LOCK-J1#s1T1 | v2 | 300 | 240.0 | 0.64 | RECOVER | RECOVERED | 0.017837 | 12.5 |
| ddc44a74090c4525a0a1d7cd1b1e8b00 | VALIDATION-LOCK-J1#s1T2 | off | 300 | - | - | - | FAILED | 0.129113 | 12.5 |
| 16e404bac52342569177b4206910430f | VALIDATION-LOCK-J1#s1T2 | v1 | 300 | 240.0 | - | - | RECOVERED | 0.027133 | 12.5 |
| a049a236f9914c2b91e8c8c48434ed4e | VALIDATION-LOCK-J1#s1T2 | v2 | 300 | 240.0 | 0.64 | RECOVER | RECOVERED | 0.010612 | 12.5 |
| 053d8fd60c214112a3049d2065d383d7 | VALIDATION-LOCK-J1#s2T1 | off | 301 | - | - | - | FAILED | 0.178664 | 12.5 |
| 11f620340c434a18a88758ca46c00179 | VALIDATION-LOCK-J1#s2T1 | v1 | 301 | 240.0 | - | - | RECOVERED | 0.002713 | 12.5 |
| b86d0ce8980a4681bc6d1aa87b91ef57 | VALIDATION-LOCK-J1#s2T1 | v2 | 301 | 240.0 | 1.04 | RECOVER | RECOVERED | 0.001524 | 12.5 |
| 4bb737be7a2341c1a75acb0d97d7b0aa | VALIDATION-LOCK-J1#s2T2 | off | 301 | - | - | - | FAILED | 0.081588 | 12.5 |
| 0c429c3654944a77b0bca07a1b035de5 | VALIDATION-LOCK-J1#s2T2 | v1 | 301 | 240.0 | - | - | RECOVERED | 0.014167 | 12.5 |
| 67a1a9af7bef471483dcba4321744126 | VALIDATION-LOCK-J1#s2T2 | v2 | 301 | 240.0 | 1.04 | RECOVER | RECOVERED | 0.007254 | 12.5 |
| f2abe904cf3f4439a34509b5cb94c41c | VALIDATION-LOCK-J1#s3T1 | off | 302 | - | - | - | RECOVERED | 0.045993 | 12.5 |
| 213f75c1a3ea4066a7ce3cdf40cfee09 | VALIDATION-LOCK-J1#s3T1 | v1 | 302 | 240.0 | - | - | RECOVERED | 0.004476 | 12.5 |
| 4a7dc9006a1141e2bacd24a2f0741379 | VALIDATION-LOCK-J1#s3T1 | v2 | 302 | 240.0 | 1.44 | RECOVER | RECOVERED | 0.01027 | 12.5 |
| 34872cee67bc46c1a7e15efdda364db8 | VALIDATION-LOCK-J1#s3T2 | off | 302 | - | - | - | RECOVERED | 0.028679 | 12.5 |
| 174d689d48d34906aff11986c68da370 | VALIDATION-LOCK-J1#s3T2 | v1 | 302 | 240.0 | - | - | RECOVERED | 0.004342 | 12.5 |
| c8eadbf148514acb82b380ac47b904d4 | VALIDATION-LOCK-J1#s3T2 | v2 | 302 | 240.0 | 1.44 | RECOVER | RECOVERED | 0.008836 | 12.5 |
| 711539655bd042eeb4e7d58f45e8be11 | VALIDATION-LOCK-J2#s1T1 | off | 300 | - | - | - | FAILED | 0.103571 | 12.5 |
| 05ce1af5498544da92f2bac8277b1e54 | VALIDATION-LOCK-J2#s1T1 | v1 | 300 | 240.0 | - | - | RECOVERED | 0.005131 | 12.5 |
| b7d61ec815c64243bb2304c3111ac54c | VALIDATION-LOCK-J2#s1T1 | v2 | 300 | 240.0 | 0.64 | RECOVER | RECOVERED | 0.001167 | 12.5 |
| 27dfba1e3eac482d89965f72ee2e7ab7 | VALIDATION-LOCK-J2#s1T2 | off | 300 | - | - | - | FAILED | 0.123032 | 12.5 |
| e26da74c039d4c6eb45ee46584083ba1 | VALIDATION-LOCK-J2#s1T2 | v1 | 300 | 240.0 | - | - | RECOVERED | 0.013578 | 12.5 |
| b9ec814804084a51940e141216cf26de | VALIDATION-LOCK-J2#s1T2 | v2 | 300 | 240.0 | 0.64 | RECOVER | RECOVERED | 0.006126 | 12.5 |
| 023cae834f0347fd8a45cd17afcefeba | VALIDATION-LOCK-J2#s2T1 | off | 301 | - | - | - | FAILED | 0.060188 | 12.5 |
| a64cb500328e4107adfc859efe12c174 | VALIDATION-LOCK-J2#s2T1 | v1 | 301 | 240.0 | - | - | RECOVERED | 0.004903 | 12.5 |
| 5b5a2d069fae45fb82caca40ded4a1dc | VALIDATION-LOCK-J2#s2T1 | v2 | 301 | 240.0 | 1.04 | RECOVER | RECOVERED | 0.004191 | 12.5 |
| 168d7981ef234ee598f5b93c11bb1e8a | VALIDATION-LOCK-J2#s2T2 | off | 301 | - | - | - | FAILED | 0.077797 | 12.5 |
| 70fe001f353b40b1958faeddec1b3bb5 | VALIDATION-LOCK-J2#s2T2 | v1 | 301 | 240.0 | - | - | RECOVERED | 0.011612 | 12.5 |
| e2cb905cfea14cab991dad00b669164a | VALIDATION-LOCK-J2#s2T2 | v2 | 301 | 240.0 | 1.04 | RECOVER | RECOVERED | 0.004783 | 12.5 |
| 31f1f72bec1a48518df1e26a34406ef0 | VALIDATION-LOCK-J2#s3T1 | off | 302 | - | - | - | RECOVERED | 0.016698 | 12.5 |
| ba17a2e7e7f0469b9379eaae1104fb5e | VALIDATION-LOCK-J2#s3T1 | v1 | 302 | 240.0 | - | - | RECOVERED | 0.002105 | 12.5 |
| 4a23d3bed4994db38bfad68adfd36587 | VALIDATION-LOCK-J2#s3T1 | v2 | 302 | 240.0 | 1.44 | RECOVER | RECOVERED | 0.009835 | 12.5 |
| 9d1b9d736348402896f922bb924ed9cf | VALIDATION-LOCK-J2#s3T2 | off | 302 | - | - | - | RECOVERED | 0.026007 | 12.5 |
| 2656c6ea5bba49e9b39102c50cb9ad13 | VALIDATION-LOCK-J2#s3T2 | v1 | 302 | 240.0 | - | - | RECOVERED | 0.005183 | 12.5 |
| 63ee806a199b46158332b4d28555afc5 | VALIDATION-LOCK-J2#s3T2 | v2 | 302 | 240.0 | 1.44 | RECOVER | RECOVERED | 0.001408 | 12.5 |
| 9d0c1131c20942de9b321c7fe438f5ef | VALIDATION-LOCK-J3#s1T1 | off | 300 | - | - | - | RECOVERED | 0.021043 | 12.5 |
| b63a357da5ba43c496d1349372fbbf88 | VALIDATION-LOCK-J3#s1T1 | v1 | 300 | 240.0 | - | - | RECOVERED | 0.005288 | 12.5 |
| ea2bc8d2af5947ecbe7364ed55ecbbfa | VALIDATION-LOCK-J3#s1T1 | v2 | 300 | 240.0 | 0.64 | RECOVER | RECOVERED | 0.003057 | 12.5 |
| 9ffaa62e9e894d218a2f148f0222ad3f | VALIDATION-LOCK-J3#s1T2 | off | 300 | - | - | - | RECOVERED | 0.018939 | 12.5 |
| 6fe7e2e8bed04e8492679f4153d831e0 | VALIDATION-LOCK-J3#s1T2 | v1 | 300 | 240.0 | - | - | RECOVERED | 0.014419 | 12.5 |
| cb77460d4a7443388399c171a0c6046f | VALIDATION-LOCK-J3#s1T2 | v2 | 300 | 240.0 | 0.64 | RECOVER | RECOVERED | 0.012126 | 12.5 |
| 3c5eaa498fa24a99810cc691c3438944 | VALIDATION-LOCK-J3#s2T1 | off | 301 | - | - | - | RECOVERED | 0.012619 | 12.5 |
| 6928ec3eac8d4aceb1a13c800082b656 | VALIDATION-LOCK-J3#s2T1 | v1 | 301 | 240.0 | - | - | RECOVERED | 0.004524 | 12.5 |
| 70f62457a5204935b00f5ad2a69f14de | VALIDATION-LOCK-J3#s2T1 | v2 | 301 | 240.0 | 1.04 | RECOVER | RECOVERED | 0.007133 | 12.5 |
| 256081a5adfc49f4ab6f9c3615ef66d2 | VALIDATION-LOCK-J3#s2T2 | off | 301 | - | - | - | RECOVERED | 0.011956 | 12.5 |
| 5956a02c38d24d888f475969a6f35a6f | VALIDATION-LOCK-J3#s2T2 | v1 | 301 | 240.0 | - | - | RECOVERED | 0.014603 | 12.5 |
| 82c1d7b2dfc94a759c941d440261cad3 | VALIDATION-LOCK-J3#s2T2 | v2 | 301 | 240.0 | 1.04 | RECOVER | RECOVERED | 0.000938 | 12.5 |
| 24ada69c31b944aeaa4a5c667158016d | VALIDATION-LOCK-J3#s3T1 | off | 302 | - | - | - | RECOVERED | 0.003814 | 12.5 |
| 8e14024b466b4cff80147cd380badece | VALIDATION-LOCK-J3#s3T1 | v1 | 302 | 240.0 | - | - | RECOVERED | 0.001694 | 12.5 |
| 1b91845e9d8541e8b846d5f74448ac7c | VALIDATION-LOCK-J3#s3T1 | v2 | 302 | 240.0 | 1.44 | RECOVER | RECOVERED | 0.01493 | 12.5 |
| be5e8690f2d0459cb21996d2ba542b54 | VALIDATION-LOCK-J3#s3T2 | off | 302 | - | - | - | RECOVERED | 0.004307 | 12.5 |
| 3aca03c02f56444690582b16d3b5bdb2 | VALIDATION-LOCK-J3#s3T2 | v1 | 302 | 240.0 | - | - | RECOVERED | 0.006371 | 12.5 |
| f020871ef6634a4f9433d7d1cb8e6fcf | VALIDATION-LOCK-J3#s3T2 | v2 | 302 | 240.0 | 1.44 | RECOVER | RECOVERED | 0.000887 | 12.5 |

## 5. 来源核验

- 冻结文件记录的 7 个实现文件哈希中，6 个与本次 `a0a6b3b` 工作树一致。
- `test/benchmarks/run_task_recovery.py` 的冻结哈希 `bfb9ccf2…` 在当前远程历史中不存在；该文件在冻结后继续有提交（新增噪声/滤波选项，默认路径不变）。
- 尽管该文件哈希不一致，本次复跑的汇总指标与冻结文件逐项相同：
  `off 11/24`、`v1 19/24`、`v2 21/24 恢复 + 3/24 安全停止`，平均检出 `240ms`，平均停止 `0.15s`。
- 因此可判定数值可复现；哈希差异已在本 manifest 的 `hashComparison` 中显式留档。

## 6. 适用范围与限制

- 数值孪生结果，不代表真实机械臂/工业现场；故障关节力矩读数为合成了 `12.5N·m` 的卡滞反力。
- validation 集冻结于运行前，但非盲测；`exploratory` 划分不得用于调参。
- 可达性规划只评价末端位置，不评价姿态；搜索失败记为 `NO_FEASIBLE_PLAN` 并转安全停止。
- 云端链路回放：见第 7 节，已通过 MQTT→后端→MySQL 验证。

## 7. 端→边→云链路回放
- 本地栈：`deploy/docker-compose.local.yml`，容器 `robot-{mysql,mosquitto,backend,nginx}-local`；MQTT `ssl://127.0.0.1:8884`，后端 `http://127.0.0.1:8090`。
- 轨迹：v2 `VALIDATION-LOCK-J0#s1T2`，run_id `e8d5d5e2a5e748ec92867b5f2ca6471f`，trace sha256 `5c95e05b…`。
- 回放：100Hz、800 帧 `sim_state`；develop-C 边端（无 ROS 2，V1 容错管线）实时消费并 10Hz 上报云。
- 边端检出：`JOINT_LOCKED joint=0`，位置极差 0.0、平均力矩 12.5N·m（高于 10N·m 阈值），10:50:09 首次确认，云端正状态为 `ERROR`。
- 云端入库：时间窗 `10:50:08–10:50:17` 内 `ROBOT-001` 遥测 **374 行**（其中 `ERROR` 367 行），批次写入 `inserted=374`、`dropped=0`、`failedFlushes=0`，明细总量 967→1341。
- 说明：回放验证的是故障状态传播、边端检出和云端入库；V2 恢复/停止的定量指标仍来自离线官方 harness（第 3 节）。首次回放因使用相对时间戳被边端拒绝，已修正为“回放起始 epoch + 相对毫秒”，800 帧全部处理成功。