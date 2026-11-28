# 成员 A 数字孪生仿真端

## 1. 模块架构

| `sim/` 下的路径 | 职责 |
| --- | --- |
| `hydraulic-arm/python_twin/hydraulic_arm_twin.py` | 数值孪生参考，提供六轴 DH、动力学参数和模型推导对应的实现。参数出处见 [parameter_sources.md](../sim/hydraulic-arm/docs/parameter_sources.md)。 |
| `gazebo_arm/gazebo_arm/gen_urdf.py`、`visual_meshes.py` | 从项目参数生成 URDF 和 COLLADA 外观网格。`urdf/hydraulic_arm.urdf` 描述关节原点、轴向、限位及连杆视觉、碰撞和惯性。网格位于 `meshes/`。 |
| `gazebo_arm/gazebo_arm/plant.py` | 六轴轻量仿真。目标经过限速与限加速度参考跟随，送入带重力前馈的 PD 内环。每个发布步长含多个积分子步。故障注入影响动力学或状态读数。 |
| `gazebo_arm/gazebo_arm/end_effector.py` | 沿 URDF 关节链计算 `base_link → link_6` 的正运动学，用于界面和记录。 |
| `gazebo_arm/gazebo_arm/plant_node.py`、`scenarios.py` | ROS 2 实时节点与作业路点。按 100 Hz 推进仿真，发布状态，接收目标，执行搬运、喷号或下料分拣预设。 |
| `gazebo_arm/gazebo_arm/scene_node.py`、`rviz/arm.rviz`、`control_panel.py` | ROS Marker 工位布景、RViz 显示配置与控制面板。面板显示关节读数、末端位姿与轨迹，在预设演示及回放模式下为只读。 |
| `gazebo_arm/scenarios/*.yaml`、`gazebo_arm/gazebo_arm/run_joint_lock.py`、`replay_joint_states.py` | 选择 YAML 定步长实验，生成 100 Hz 的 CSV。回放器读取位置、速度、力矩并重新发布为 `JointState`，供 RViz 和状态消费者使用。 |
| `gazebo_arm/launch/sim_arm.launch.py` | 启动轻量 plant 或 CSV 回放、`robot_state_publisher`，按参数加开 RViz、控制面板和场景 Marker。 |
| `gazebo_arm/launch/gazebo.launch.py`、`urdf/gazebo_arm.gazebo.xacro`、`config/arm_controllers.yaml`、`worlds/steel_yard.world` | Gazebo Classic 路径的生成、控制器和钢材工位配置。`gazebo_bridge.py` 复用对外话题。独立的 `grasp_node.py` 提供工件跟随演示。 |
| `gazebo_arm/setup.py`、`package.xml` | 安装 ROS 包、节点、模型与启动资源。 |

## 2. 对成员 B 的接口

默认设备标识为 `SIM-001`，ROS 2 话题段使用 `SIM_001`。字符串中除字母、数字和下划线以外的字符统一替换为下划线。实时节点的收发队列深度均为 10。

| 方向 | 话题 | ROS 2 消息类型 | 字段及约定 |
| --- | --- | --- | --- |
| B → 仿真 | `/simulation/SIM_001/joint_command` | `std_msgs/msg/Float64MultiArray` | `data` 为六个有限的目标角，顺序 `joint_1` 至 `joint_6`，单位 rad。长度错误或含非有限值时忽略。外部控制时使用默认空 `scenario` 和 `demo:=false`，避免预设继续写入目标。 |
| 仿真 → B、边端 | `/simulation/SIM_001/joint_states` | `sensor_msgs/msg/JointState` | `header.stamp` 取 ROS 节点时钟。`name` 为同序六轴，`position`、`velocity`、`effort` 分别使用 rad、rad/s、N·m。实时发布按配置为 100 Hz。传感器漂移可影响位置读数。 |
| 仿真 → 可视化 | `/tf`、`/tf_static` | `tf2_msgs/msg/TFMessage` | `robot_state_publisher` 结合 URDF 和 `JointState` 产生连杆坐标变换。 |

故障默认关闭。布尔开关和卡滞参数由轻量启动脚本传入。漂移速率、磨损增益和扰动力矩幅度属于 `plant_node` 的细调参数。

| 参数 | 默认值 | 行为 |
| --- | --- | --- |
| `fault_lock_joint`、`fault_lock_at` | 空、0.30 s | 指定 `joint_1` 至 `joint_6` 中的一轴。在达到设定仿真时间的首个积分前锁定当前角度，速度清零，其余轴继续积分。仍可观察被锁轴的执行器力矩。 |
| `fault_sensor_drift`、`fault_drift_rate` | `false`、0.02 rad/s | 启用后 J1 以设定速率漂移，J2 以其一半漂移，读数噪声配置为 0.002 rad 标准差。 |
| `fault_actuator_wear`、`fault_wear_gain` | `false`、0.6 | 启用后 J3 执行器增益降低，附加摩擦系数配置为 2.0。 |
| `fault_disturbance`、`fault_disturbance_torque` | `false`、8.0 N·m | 启用后在 J2 动力学中叠加扰动力矩。 |

## 3. 对成员 C 的接口与记录格式

仿真端把实时 `JointState` 推给边端。边端按默认 10 Hz 将状态转发到 MQTT `simulation/{simulationId}/state`，使用设备标识原值（如 `SIM-001`）。上行 JSON 含 `simulationId`、`robotId`、Unix 毫秒 `timestamp`、六元素 `jointPosition`（rad）、`jointVelocity`（rad/s）、`jointTorque`（N·m）、`status` 和活动故障数组 `faults`。活动故障字段为 `faultType`、零起点 `jointIndex`、`severity`、Unix 毫秒 `timestamp` 和 `detail`，由边端检测链路填充。[MQTT 契约](mqtt-contract.md) · [边端上行实现](../edge/edge_node/edge_node/main.py)

离线实验数据以 [正常实验](../member-a-delivery/runs/point-to-point-normal-95ef64c016994260b7ba18861c59da67/states.csv) 和 [肩轴卡滞实验](../member-a-delivery/runs/point-to-point-shoulder-lock-25d80a6e39bb485ba11daa0624be0b68/states.csv) 为准，各 800 行状态，首条时间 0.01 s，末条 8.00 s。较早的同目录记录只包含关节状态。末端字段以下表对应的当前基线为准。

| `states.csv` 列 | 含义 |
| --- | --- |
| `run_id` | 本次运行的唯一标识，与事件和元数据关联。 |
| `tick`、`sim_time_s` | 积分后的采样编号，从 1 起。仿真相对时间为 `tick × 0.01` s。 |
| `joint_{1..6}_target_rad` | 当步目标关节角，单位 rad。 |
| `joint_{1..6}_position_rad` | 当步上报关节角，单位 rad。 |
| `joint_{1..6}_velocity_rad_s` | 当步上报关节角速度，单位 rad/s。 |
| `joint_{1..6}_effort_Nm` | 当步执行器力矩读数，单位 N·m。 |
| `ee_x_m`、`ee_y_m`、`ee_z_m` | 根据六轴位置正解得到的 `link_6` 原点在 `base_link` 下的位置，单位 m。 |
| `ee_roll_rad`、`ee_pitch_rad`、`ee_yaw_rad` | 同一坐标变换的固定轴欧拉角，单位 rad，旋转矩阵为 Rz(yaw) Ry(pitch) Rx(roll)。 |

| [`events.csv`](../member-a-delivery/runs/point-to-point-shoulder-lock-25d80a6e39bb485ba11daa0624be0b68/events.csv) 列 | 含义 |
| --- | --- |
| `run_id` | 与本次 `states.csv` 一致。 |
| `event` | 事件名，当前为 `joint_locked`。正常实验只有表头。 |
| `tick`、`sim_time_s` | 注入发生在该时刻之后的积分前。基线为 tick 30、0.30 s，首条受锁影响的状态是 tick 31。 |
| `joint`、`position_rad` | 被锁关节名与锁定角。基线为 `joint_2`、0.35131841120386753 rad。 |

每次实验还写入 `metadata.json`，包含工况名、初始与目标角、步长、步数、参考速度上限和锁轴信息。当前记录器也附末端参考坐标及 URDF SHA-256。`events.csv` 是离线注入事件，MQTT `faults` 是实时检测状态。

当前 URDF 的末端位姿对照使用 `member-a-delivery/runs-dh-verified/`。两套归档的 800 帧关节数据与锁轴事件一致。`runs/` 所录末端字段与当前 URDF 的正解存在差异，YAML 迁移前已复现。迁移前后的双基线对照见 [YAML 场景验证记录](member-a-scenario-validation.json)。

## 4. 运行手册

以下命令在 Windows PowerShell 7、RoboStack ROS 2 Humble 环境验证。从仓库根目录运行。现有 Pixi 清单和可执行文件位于本机 `%LOCALAPPDATA%\SimPlatformROS`。第一段进入已激活的子 PowerShell。

```powershell
$ros = Join-Path $env:LOCALAPPDATA 'SimPlatformROS'
$pixi = Join-Path $ros 'pixi.exe'
& $pixi run --manifest-path (Join-Path $ros 'pixi.toml') pwsh -NoProfile
```

在该子 PowerShell 中构建并加载仓库中的仿真包。构建输出保存在用户目录中的独立工作区。

```powershell
$ErrorActionPreference = 'Stop'
$repo = (Get-Location).Path
$env:PYTHONUTF8 = '1'
$env:ROS_LOCALHOST_ONLY = '1'
$env:ROS_DOMAIN_ID = '76'
$workspace = Join-Path $env:LOCALAPPDATA 'SimPlatformROS/member-a-workspace'
colcon --log-base (Join-Path $workspace 'log') build --merge-install --base-paths (Join-Path $repo 'sim/gazebo_arm') --packages-select gazebo_arm --build-base (Join-Path $workspace 'build') --install-base (Join-Path $workspace 'install')
if ($LASTEXITCODE -ne 0) { throw 'gazebo_arm build failed' }
. (Join-Path $workspace 'install/local_setup.ps1')
ros2 pkg prefix gazebo_arm
```

正常搬运使用七路点、单次运行。退出该命令后，再启动下一模式。

```powershell
ros2 launch gazebo_arm sim_arm.launch.py rviz:=true panel:=true scene:=false scenario:=handling scenario_loop:=false
```

实时卡滞演示在搬运过程中于 3.40 s 锁住肩轴。两种实时模式均启动 RViz 与只读面板。

```powershell
ros2 launch gazebo_arm sim_arm.launch.py rviz:=true panel:=true scene:=false scenario:=handling scenario_loop:=false fault_lock_joint:=joint_2 fault_lock_at:=3.4
```

离线定步长实验加载本包 `scenarios/` 下的 YAML，从 HOME 每 0.01 s 积分一次。命令不带参数时只列出场景。指定 `--scenario` 后按文件名选择工况，并在输出根目录中新建 `output_dir-运行ID` 子目录。

| 配置 | 路点与时长 | 故障 |
| --- | --- | --- |
| [handling.yaml](../sim/gazebo_arm/scenarios/handling.yaml) | 点到点搬运实验，1 个目标，8.00 s、800 帧。 | 无 |
| [lock.yaml](../sim/gazebo_arm/scenarios/lock.yaml) | 沿用点到点实验目标，8.00 s、800 帧。 | 0.30 s 锁定 `joint_2` |
| [elbow_grasp.yaml](../sim/gazebo_arm/scenarios/elbow_grasp.yaml) | HOME、接近、深弯取件姿态、抬起撤离、回 HOME，10.50 s、1050 帧。 | 无 |

每个路点包含名称、`joint_1` 到 `joint_6` 的目标角 `position_rad` 和固定时长 `duration_s`。角度按 URDF 限位检查，时长与故障注入时刻须是 0.01 s 的整数倍。多路点记录的 `metadata.json` 中 `target_position_rad` 为最后一个目标，逐帧目标取 `states.csv`。旧命令中的 `--lock` 仍指卡滞实验，只传 `--output` 仍默认正常实验。

```powershell
$output = Join-Path $workspace 'scenario-runs'
python -m gazebo_arm.run_joint_lock
if ($LASTEXITCODE -ne 0) { throw 'Scenario listing failed' }
foreach ($name in 'handling', 'lock', 'elbow_grasp') {
    python -m gazebo_arm.run_joint_lock --scenario $name --output $output
    if ($LASTEXITCODE -ne 0) { throw "Scenario failed: $name" }
}
```

在已激活的子 PowerShell 中回放卡滞基线，以 `JointState` 重放记录序列。

```powershell
$csv = (Join-Path $repo 'member-a-delivery/runs/point-to-point-shoulder-lock-25d80a6e39bb485ba11daa0624be0b68/states.csv').Replace('\', '/')
ros2 launch gazebo_arm sim_arm.launch.py rviz:=false scene:=false "replay_csv:=$csv"
```

## 5. 渲染产物

| `render/outputs/` 中的产物 | 数据来源与规格 |
| --- | --- |
| [`frames/pose_home.png`](../render/outputs/frames/pose_home.png) | 搬运记录 `handling-no-fault.csv` 第 1 帧，1600×1200。 |
| [`frames/pose_elbow_bent.png`](../render/outputs/frames/pose_elbow_bent.png) | 同一搬运记录第 766 帧，1600×1200。 |
| [`frames/pose_shoulder_lock.png`](../render/outputs/frames/pose_shoulder_lock.png) | 卡滞基线第 150 帧，1600×1200。 |
| [`animations/normal_cycle.mp4`](../render/outputs/animations/normal_cycle.mp4)、[`animations/lock_event.mp4`](../render/outputs/animations/lock_event.mp4) | 分别来自两组 800 帧基线。按源时间线性插值到各 300 帧，1920×1080、30 fps、10 s。 |

再生成时在保留相对路径的工作副本根目录执行。脚本从 [`product_final_v2.blend`](../render/checks/product_final_v2.blend) 读取正式场景和已打包的 HDRI。先重渲静帧，再生成并检查两张动画预检图，最后运行全量动画入口。该入口可复用同一场景及数据对应的逐帧缓存，最后用 PATH 中的 ffmpeg 编码并由 ffprobe 校验。产物相对路径与验证证据见 [渲染交付清单](../render/DELIVERY.md)。

```powershell
$blender = Join-Path $env:LOCALAPPDATA 'SimPlatformBlender/blender-4.5.5-windows-x64/blender.exe'
$scene = 'render/checks/product_final_v2.blend'
& $blender -b $scene --python-exit-code 1 -P render/render_stills.py
& $blender -b $scene --python-exit-code 1 -P render/animate_from_csv.py -- --preview
& $blender -b $scene --python-exit-code 1 -P render/animate_from_csv.py
```

## 6. 已知限制

- 外观和连杆由仓库参数表、URDF 和自建 COLLADA 网格构成。项目缺少原厂 CAD 与外形公差资料。
- 轻量仿真用于关节运动和位姿验证。Gazebo 接触物理、夹持力与释放稳定性未通过验证。
- URDF 的双指夹爪开度为固定演示预设。抓取演示中的接近、取件和撤离来自关节路点，夹爪开合与接触力不在六轴记录中。
