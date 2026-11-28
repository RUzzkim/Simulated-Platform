# 成员 A 六关节仿真与卡滞回放执行方案

当前开发进度在 `feature/a-joint-lock`。正常与卡滞各 800 帧已生成并核验，记录包含 `base_link` 到 `link_6` 的末端位姿。Windows 上的 ROS 2 Humble 已构建仿真包并完成卡滞回放验证，RViz 已成功启动。可在 PowerShell 执行 `& "$env:LOCALAPPDATA\SimPlatformROS\play-replay.cmd"` 重播。通用运行命令见仓库 [仿真端 README](../sim/gazebo_arm/README.md#单关节卡滞记录与回放)。

实时交互可用 `& "$env:LOCALAPPDATA\SimPlatformROS\live-panel.cmd"` 启动。无参数为六轴手动控制，参数 `handling` 为正常搬运，参数 `lock` 为搬运过程中肩关节卡滞。面板显示六轴读数和末端位姿，RViz 跟踪实际末端轨迹。

运动学已按数值孪生的标准 DH 参数修正。需要末端位姿时使用 `runs-dh-verified/` 中重新生成的数据。旧运行目录的关节角可回放，旧末端位姿对应修正前的 URDF。新运行的 `metadata.json` 记录对应 URDF 的 SHA-256。

先完成一个可以在 Windows 上独立运行的六轴仿真。用同一段轨迹分别生成无故障和单关节卡滞两份记录，再从记录生成对比回放。第一批工况复现旧实验的肩关节卡滞，搬运场景用于展示完整作业节拍。

## 现状与起步命令

仓库在 `C:\Users\hj\orca\projects\Simulated-Platform`，执行基线为 `master` 的 `ea4db18`。

```powershell
Set-Location 'C:\Users\hj\orca\projects\Simulated-Platform'
git status --short --branch
git rev-parse --short HEAD
py .\sim\gazebo_arm\gazebo_arm\plant.py
```

已在 Windows 实测，最后一行应显示三类故障和扰动注入测试通过。单次目标及 100 Hz 流式目标均在 10 秒内收敛并保持，末位误差约为 0.0001 rad。六个转动关节已从 URDF 核对为 `joint_1` 至 `joint_6`。同目录的 [正常搬运 CSV](handling-no-fault.csv) 和 [回放曲线](handling-no-fault.png) 来自同一版 Python plant，包含 7 个路点、8.50 秒、850 帧。曲线第一栏虚线为目标角，实线为实测仿真角。

| 文件 | 用法 |
|---|---|
| `sim/gazebo_arm/gazebo_arm/plant.py` | 六轴动力学和目标跟随。每帧 10 ms，内部 10 个积分子步。现有故障为传感器漂移、执行器磨损与外力矩扰动，位置卡滞需新增 |
| `sim/gazebo_arm/gazebo_arm/scenarios.py` | 复用 `handling` 搬运路点，建立固定步长的场景执行入口 |
| `sim/gazebo_arm/gazebo_arm/plant_node.py` | ROS 2 封装。当前路点调度使用墙钟，适合演示。重复实验使用离线固定步长入口 |
| `sim/gazebo_arm/urdf/hydraulic_arm.urdf` | 复用六轴几何和关节名。回放的末端位姿统一定义为 `base_link` 到 `link_6` |

## 先冻结一对工况

| 工况 | 轨迹和时间 | 验证内容 |
|---|---|---|
| `point-to-point-normal` | 从仓库 `HOME` 出发，以 0.6 rad/s 的参考速度上限，去往 `[0.8, 0.6, -0.5, 0.4, 0.3, 0.2]`。时长 8 s，采样 100 Hz，记录种子 100。若启用随机扰动，使用该种子初始化 | 六轴数据有效，路点指令可跟随，生成正常对照 |
| `point-to-point-shoulder-lock` | 同起点、目标、速度上限、步长和种子。第 30 个仿真步开始前，即 `t=0.30 s`，冻结 `joint_2` 至结束。步号从 0 计 | 锁定角维持在注入瞬间的角度，锁定轴速度为零，其他轴可继续运动 |

旧实验 `LOCK-J1#s1T1` 使用从 0 开始的关节索引，索引 1 对应 URDF 的 `joint_2`。这里借用它的工况参数。旧实验使用了不同的仿真被控对象和轨迹实现，旧报告数值只作背景，新结果按实时仿真模型单独记录。

已用上述正常配置独立跑完 800 步。六轴最终误差最大值为 `0.000294 rad`，注入时刻前的肩关节角约为 `0.351318 rad`，可作为首次接入卡滞时的对照值。

## 实施顺序

1. **11 月 25–26 日，冻结正常基线。** 保留六轴冒烟输出和搬运回放。在离线入口复用 `RealtimePlant`，用步号推进时钟并下发路点，记录仓库提交、场景和配置。正常点到点工况先验收六轴末端关节角与目标差值均小于 `0.01 rad`。这个值仅用于 A 的仿真冒烟。
2. **11 月 27–28 日，接入位置卡滞。** 在 `FaultInjector` 配置锁定关节及触发步号，在 `RealtimePlant.step` 生效。进入故障时保存该轴当前角度，每个物理子步固定位置和速度，只求解健康轴加速度。沿用现有 `effort` 的执行器输出含义。加一条回归检查，确认故障关闭时仍通过原冒烟。
3. **11 月 29 日–12 月 3 日，落盘并回放。** 离线入口接受场景、种子和输出目录，以 `run_id` 建目录。输出 `metadata.json`、`states.csv`、`events.csv` 和 `replay.png`。用 CSV 绘制关节指令与实测角、速度和力矩，在图上标出注入时刻。添加基于 URDF 的末端位姿记录，用已知姿态校验坐标系和单位。
4. **12 月 4–6 日，出展示素材。** 对同一段轨迹并排播放正常和卡滞记录，突出卡滞轴、注入时间和健康轴运动。使用 ROS 2 Humble 和现有 launch 启动 RViz 作三维演示。
5. **12 月 7–9 日，冻结 A 的交付。** 从一份干净检出复跑，交付命令、两个运行目录、对比图和简短回放。若卡滞实现尚在调试，交付记录注明当前可复现的工况和未通过的检查。

## 验收检查

- 正常和卡滞两个点到点工况均为 8 秒、800 帧。首帧是第一个积分区间结束时的状态，最后一帧为 8.00 秒。每帧六轴位置、速度、执行器力矩和指令均为有限数，时间戳按步号递增。
- 文件中的关节名保持 `joint_1` 至 `joint_6`。角度、速度、力矩分别使用 rad、rad/s、N·m，末端位置用 m。
- 注入前两份记录吻合。注入事件只出现一次，事件记录包含 `run_id`、步号 30、`0.30 s`、`joint_2` 和锁定角。注入后的锁定轴位置偏差和速度绝对值分别低于 `1e-6 rad` 和 `1e-6 rad/s`。健康轴中至少一轴在窗口内仍有可测运动。
- 同一提交和配置连续运行两次，忽略运行编号和生成时间后，状态序列及注入事件一致。回放仅用已落盘数据即可重建。原始 CSV 和对比图都随运行记录保留。

## ROS 2 可视化

在已安装 ROS 2 Humble 的 Ubuntu 环境中，把 `sim/gazebo_arm` 放入 colcon 工作区的 `src/` 后运行。

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select gazebo_arm
source install/setup.bash
ros2 launch gazebo_arm sim_arm.launch.py sim_id:=SIM-001 rviz:=true scenario:=handling
```

另开一个已加载 ROS 2 的终端，运行 `ros2 topic hz /simulation/SIM_001/joint_states`。现有 ROS 2 launch 可以演示正常搬运。新增的卡滞回放先验收离线数据与曲线，之后在同一个 RViz 机械臂模型上展示。
