# gazebo_arm — 轻量实时仿真端（「端」层）

「端—边—云」里的**端**:一个 ROS2 节点,实时仿真 6R 液压机械臂,产生关节状态、
接收关节指令,供边端(`edge/edge_node`)对接。这是原先缺失的实时端的第一版
(方案:轻量实时端——复用已验证的动力学 + DH 几何,不追 Gazebo 物理引擎)。

## 接口(与边端 ROS2 契约对齐)

见 `edge/edge_node/docs/edge_cloud_integration.md`。本节点与边端互为收发:

| 方向 | Topic | 类型 | 内容 |
|---|---|---|---|
| 端→边 | `/simulation/{sim_id}/joint_states` | `sensor_msgs/JointState` | position/velocity/effort[6] + stamp,100Hz |
| 边→端 | `/simulation/{sim_id}/joint_command` | `std_msgs/Float64MultiArray` | 6 个目标关节角(rad) |

关节名 `joint_1..joint_6`,`sim_id` 默认 `SIM-001`。

## 动力学与几何从哪来(复用,非新造)

- **动力学**:`plant.py` 镜像 `edge/edge_node/test/simulation_simulator.py` v2.3 的
  轻量稳定模型——每关节二阶 + 内环 PD(Kp=50/Kd=10) + 余弦重力 + 粘性/库仑/Stribeck
  摩擦 + 相邻关节 M(q) 惯量耦合 + 科氏项;1kHz 子步半隐式积分。
- **目标跟随(与参考仿真端的唯一差异)**:参考端对每条指令做一次性梯形规划;本端改为
  在线限速/限加速度跟随(`RefFollower`)。原因:边端 `adaptive_nn` 模式的控制循环
  100Hz 连续下发 `joint_command`,一次性规划每 10ms 被重置、参考停在起点,臂根本不动
  (已在本机复现)。单次下发时行为等价梯形规划。
- **几何**:`gen_urdf.py` 从 `sim/hydraulic-arm` 数值孪生的 DH + 连杆质量/惯量生成
  `urdf/hydraulic_arm.urdf`,与孪生同源。
- **为什么不用液压孪生做 plant**:那套在保持段有未解决的执行器欠阻尼失稳
  (见 `sim/hydraulic-arm/README.md §4.5`),不适合需要长时间稳定保持位姿的实时端。

## 构建 / 运行(需 ROS2 环境)

本机是 Windows、无 ROS2,**跑不了**;在 `ros:humble`(边端同款)里:

### 方式一:Docker(推荐,不用手装 ROS2)

在一台 Ubuntu(或 Windows 的 WSL2 Ubuntu)上装好 Docker 后,确认 MQTT broker 已在该环境的 `localhost:1883` 监听。Compose 不会启动 broker。随后把**端+边**一起起:

```bash
cd sim/gazebo_arm
docker compose up --build -d      # 后台启动 sim_end(端) + edge_node(边)
docker logs -f edge_node          # 查看边端的故障定位和恢复决策
# 在另一个终端验证端在发关节状态:
docker exec -it sim_end bash -lc 'source /opt/ros/humble/setup.bash && ros2 topic echo /simulation/SIM-001/joint_states'
```

只跑端(不带边):`docker build -t gazebo_arm:latest . && docker run --rm --network host -e EDGE_SIMULATION_ID=SIM-001 gazebo_arm:latest`。
容器内是无界面模式(不起 RViz);要三维可视化用带桌面的镜像/WSLg,见下。

### 方式二:原生 apt(Ubuntu 22.04)

```bash
colcon build --packages-select gazebo_arm   # 放进 colcon workspace 的 src/ 下
source install/setup.bash
# 看动画：起 plant + RViz，demo 模式让臂每 4s 在 home/target 间来回动
ros2 launch gazebo_arm sim_arm.launch.py rviz:=true demo:=true
# 接边端联调（不自娱自乐，由边端下发 command 驱动）：
ros2 launch gazebo_arm sim_arm.launch.py sim_id:=SIM-001
# 改了孪生 DH/质量后重新生成 URDF：
python3 gazebo_arm/gen_urdf.py
```

启动后:plant 节点发 `joint_states`、收 `joint_command`;`robot_state_publisher`
把状态转 TF 供 RViz 显示。边端以 ROS2 模式起来即可与之闭环。

## 验证状态(如实)

- **已在本机验证**:`plant.py` 独立冒烟——单次下发与 100Hz 流式下发两种用法,10s
  均收敛(误差 <1e-4)、稳定保持、无发散;`gen_urdf.py` 生成的 URDF XML 合法(6 关节/7 连杆)。
- **已在本机验证(无 ROS 的算法闭环)**:边端 `AdaptiveNNController`(默认参数)直接驱动
  plant,100Hz、60s:约 3s 进入 0.03 rad,之后误差有界(≤0.016 rad)、峰值力矩 9.3 N·m。
  稳态有 ~0.1 rad/s 的小幅游动,来自边端 NN 在线学习,不是 plant 问题。
- **已在本机验证(Docker ROS2 闭环)**:`docker compose up` 起 `sim_end`+`edge_node`
  (host 网络 + `ipc: host`,同 `ROS_DOMAIN_ID`),边端 `adaptive_nn` 默认参数经 ROS2
  订阅 `joint_states`、以 ~94Hz 下发 `joint_command`,plant 从 HOME 收敛到 setpoint 附近
  并稳定保持(|q|≤0.025 rad、保持力矩 joint_2≈6.8 N·m 远低于 50 N·m 上限),两容器
  0 重启。`plant_node`/`robot_state_publisher`/`launch` 均正常起(URDF 7 连杆解析、TF 发布)。
- **已在本机验证(native WSL2 Ubuntu 22.04 + ROS2 Humble)**:`colcon build` 通过;
  `ros2 launch gazebo_arm sim_arm.launch.py demo:=true` 起 `plant_node`+`robot_state_publisher`
  正常,`demo:=true` 下采样确认关节每 4s 在 home↔target 间干净切换(joint_1 ~0.0↔0.50、
  joint_2 ~0.35↔0.85…),即 RViz 会渲染的运动内容;WSLg 显示就绪(`DISPLAY=:0`)。
- **外观已工业化(基本体,2026-09-26)**:`gen_urdf.py` 从「一串等粗圆柱」改为钢铁车间工业臂观感：
  - **结构**：厚重地面法兰盘 + 4 地脚螺栓的底座、每关节壳含两端密封盖(IP67 防尘)、
    指向下一关节的连杆体、大臂/前臂背侧线缆保护套。
  - **夹爪总成**(独立连杆 fixed 关节，腕→底座板→左右手指)：底座板(安全黄) + 联动杆(银) +
    左右**扁平手指**(钢色主体 + 内侧**近黑硬化夹持面** + 背面驱动槽) + 腕部力/扭矩传感器(蓝) +
    指端视觉传感器(相机)。手指固定在额定张开位；做成 prismatic 可开合需 7 轴夹爪控制器
    (超出 6-DOF 端边云契约，属后续)。
  - **RAL 配色**(内联，RViz 正常显示)：主体安全黄 1003 / 关节深灰 7016 / 腕部金属银 9006 /
    夹爪硬化钢 7015 / 底座深灰 / 顶部警示红环 3020。
  - **夹爪按场景可调**：`python gen_urdf.py --preset general|sorting|marking|docking`
    (或 `--fingers/--opening/--groove`)——分拣长指大开口且夹持面为 **V 型槽**(卡圆钢管)、
    喷号短指小开口、对接精度优先。
  - **胶囊碰撞体**：每根连杆用「圆柱+两端球」逼近胶囊、带余量，套一层粗略凸的「防碰撞紧身衣」
    (URDF 无 capsule 基本体，此为标准近似)，比逐视觉体做碰撞更省，供后续运动规划/避障用。
  - **关节轴/质心=工业标准**：6 个关节轴均 `0 0 1`(DH z 约定)，关节位姿按 DH (a,0,d)+rpy(α,0,0)；
    质量/质心/惯量取自数值孪生(link_1..6：110/55/32/12/6/5 kg)，物理同源。
  - 仍是基本体近似(无 CAD 网格/无 Gazebo PBR 金属度贴图)。`robot_state_publisher` 解析无报错(10 连杆)。
    重生成后 native 需 `colcon build` 再重启 launch 生效。
  - 注：夹持力 50~500N、开合驱动属**物理/第 7 轴**范畴，当前 6-DOF 契约下夹爪为固定几何(不改边端契约)。

## 本机环境搭建(WSL2,已在本机跑通)

> 本机原 WSL Ubuntu 磁盘丢失,用**离线导入**重装(绕开 `wsl --install` 卡在 GitHub 清单
> `0x80072ee2` 的问题);apt/ROS2 源走清华镜像绕开本机代理对官方源的 502。

```powershell
# 1) 直连下 Ubuntu 22.04 WSL rootfs（cloud-images 官方站，约 234MB）后导入
wsl --import Ubuntu-22.04 E:\WSL\ubuntu-2204 <rootfs.tar.gz> --version 2
```
```bash
# 2) 进 Ubuntu 后：换清华 apt 源 + 加 ROS2 源（key 可从 ros:humble 镜像的
#    /usr/share/ros-apt-source/ros2.sources 取，改 URIs 为清华、Types 去掉 deb-src）
#    装 desktop + colcon，拷包到 ~/ros2_ws/src 下 colcon build
```

## 下一步

- [x] **阶段 1 可视化 + 外观改善**:人工在 RViz 确认臂在 home↔target 摆动(2026-09-26 已看);
      `gen_urdf.py` 已把外形从等粗圆柱改为工业臂观感(底座/关节壳/连杆体/末端 + 配色,基本体近似,
      无 CAD 网格)。重生成后 native 需 `colcon build` 再 `rviz:=true` 看新外形。
- [x] **阶段 3 端→边→云(mTLS)已打通(Docker,2026-09-26)**:边端经 `docker-compose.cloud.yml`
      改连本机云端 broker(`ssl://localhost:8884` + 设备证书 CN=SIM-001),mTLS 握手通过、
      broker 按证书 CN 命中 ACL;云端后端订阅 `simulation/SIM-001/state` 并入库
      (`telemetry_data` 中 device ROBOT-001/SIM-001 的行以 ~10Hz 实时增长)。
      起法:`docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d`。
- [x] **全链路双向闭环已打通(Docker + 云端页面,2026-09-26)**:
      - 上行:sim → 边(ROS2)→ broker(mTLS)→ 后端 → 库 → 前端。设备详情页显示 SIM-001
        遥测、`ONLINE`、健康评分、力矩趋势;历史曲线卡片新增指标下拉(位置/速度/力矩/**振动**),
        振动数据经后端重建后已落库(`joint_payload` 带 `vibration`),最近窗口曲线可见。
      - 下行:前端下发 `MOVE_JOINT` → 后端 → broker → 边(NN setpoint)→ sim,实测臂 6s 内
        收敛到目标(下发 [0.4,0.4,-0.4,0.3,0.2,0.1] → 实到 [0.380,0.380,-0.413,0.298,0.212,0.112])。
      - 注:后端镜像原为 9-20 旧版(不落振动),已用当前源码重建;前端加指标下拉后用
        `node:20` 容器 `vite build` 重生成 `dist`(nginx 绑定挂载,刷新即生效)。
- [ ] **振动趋势表**(`/trend?metric=vibration`,2h 分桶)需累积几小时历史才非空;振动**曲线**
      (历史曲线卡片)已可用,不受此限。
- [ ] **故障/告警**:仅在真实故障发生时才有数据(当前 `faults: []`);要看需人为诱发故障。
- [ ] **阶段 2/3 搬到 native(可选)**:同一 Ubuntu 里把 `edge/edge_node` build 进 `~/ros2_ws`,
      native 起端+边(不需要 `ipc: host`,DDS 同 host 直接可达);功能已在 Docker 验证,native 仅去容器化。
- [ ] **观察点**:到位后稳态 ~0.1 rad/s 小幅游动来自边端 NN 在线学习,联调不受影响,
      但送到边端做故障检测时这段数据要留意(是否误触发)。已实测 `faults: []` 未误报。

## 作业场景预设 + 故障/扰动注入（对齐项目书「端：模拟不同作业任务/传感器异常/执行器故障/外部扰动」）

端不再只是「跟踪任意目标」，可切作业场景、可开关注入故障，产生「不同工况」数据喂边/云。

**作业场景**（关节空间路点循环下发，`scenarios.py`）：`handling`(钢料搬运 pick-and-place)、
`marking`(钢坯喷号)、`sorting`(下料分拣)。示范位姿手工设定（非精确 IK），只为形成可复现节拍。

**故障/扰动注入**（`plant.py` 的 `FaultInjector`，默认全关，逐关节可配，只改物理/读数不碰控制）：
- `传感器漂移`：上报位置 = 真值 + 漂移速率·t + 噪声（高温粉尘信号漂移）；
- `执行器磨损`：实际出力打折(gain<1) + 附加摩擦（欠驱动）；
- `外部扰动`：动力学叠加外力矩（工件重量波动/碰撞）；
- `单关节卡滞`：到达指定仿真时间后冻结 J1..J6 中一个关节的位置和速度，其余关节继续运动。锁定轴 effort 报告可配置的合成反作用力矩读数，默认 12.5 N·m，用于触发现有边缘端卡滞检测阈值；它不是来自真实力传感器的测量。

初始关节姿态可用 `initial_joint_positions` 配置，取 6 个逗号分隔的弧度值。默认保持原姿态 `[0, 0.35, -0.72, 0.20, 0, 0]`。卡滞关节编号使用 J1..J6，与状态数据中的 0..5 索引相差 1。

用法（launch 参数）：
```bash
# 跑搬运场景 + 看动画
ros2 launch gazebo_arm sim_arm.launch.py rviz:=true scenario:=handling
# 喷号场景 + 注入执行器磨损（喂边端容错 / 云端健康分析）
ros2 launch gazebo_arm sim_arm.launch.py scenario:=marking fault_actuator_wear:=true
# 从默认初始姿态开始，首次收到非初始目标 1 秒后注入 J2 卡滞
ros2 launch gazebo_arm sim_arm.launch.py fault_joint_lock:=true fault_joint_lock_index:=2 fault_joint_lock_onset_s:=1.0 fault_joint_lock_after_first_command:=true
# 也可单独细调：ros2 run gazebo_arm plant_node --ros-args -p fault_disturbance:=true -p fault_disturbance_torque:=10.0
```
Docker 端边联调用法（在 `sim/gazebo_arm` 目录执行；Compose 默认启用 J2 卡滞、`pass_through` 控制和任务恢复。注入计时从边端首次下发运动目标后开始）：
```powershell
docker compose up --build -d
```
MQTT broker 必须已运行，并能从边端容器通过 `localhost:1883` 访问；Compose 不会启动 broker。启动后，在已有 broker 上下发恢复案例（关节角单位为弧度）：
```bash
mosquitto_pub -h localhost -t simulation/SIM-001/command -m '{"commandId":"CMD-FAULT-RECOVERY-001","simulationId":"SIM-001","robotId":"ROBOT-001","cmdType":"MOVE_JOINT","jointTarget":[0.2,-0.1,0.8,0.0,-0.2,0.0]}'
```
在另一个终端查看 `docker logs -f edge_node`，应看到 J2 的 `JOINT_LOCKED` 故障和 `RECOVER` 决策。STOP 搜索案例需与恢复案例分开运行，每次先执行 `docker compose down`，再重新执行 `docker compose up --build -d`，然后发送：
```bash
mosquitto_pub -h localhost -t simulation/SIM-001/command -m '{"commandId":"CMD-FAULT-STOP-001","simulationId":"SIM-001","robotId":"ROBOT-001","cmdType":"MOVE_JOINT","jointTarget":[-1.106891,-2.193779,0.948349,-2.686462,0.225453,-0.843902]}'
```
J2 卡滞后，该目标在当前搜索条件下应得到 `STOP / NO_FEASIBLE_PLAN`。这表示规划器未在其搜索范围内找到满足末端位置容差的方案，不构成数学上的不可达证明。结束后执行 `docker compose down`。

已本机离线验证：在 Compose 默认初始姿态、首条运动指令启动注入计时的条件下，边缘检测器可定位到 J2；恢复案例得到 `RECOVER`，plant 闭环跟随后末端位置误差不超过 5 mm；STOP 案例得到 `STOP / NO_FEASIBLE_PLAN`，表示当前搜索条件下未找到可行方案。当前工作站 Docker daemon 未运行，Docker/ROS 2 在线端边联调尚未验证。

## Gazebo 物理仿真骨架（进行中，2026-09-26）

按项目书把「端」从轻量 RViz plant 升级到 Gazebo 物理仿真的**骨架**。当前状态：

**环境（已就绪）**：WSL2 Ubuntu-22.04 装好 Gazebo Classic 11 + `ros2_control` + `gazebo_ros2_control` +
`xacro`；**GPU 加速可用**（`glxinfo` 显示 `D3D12 (RTX 3050)`，非软渲染）。

**已建文件**：
- `urdf/gazebo_arm.gazebo.xacro`：include 生成的 `hydraulic_arm.urdf` + `world` 锚点固定关节 +
  6 关节 `ros2_control`(position 命令 / position·velocity·effort 状态) + `gazebo_ros2_control` 插件 + Gazebo 材质色。
- `config/arm_controllers.yaml`：`joint_state_broadcaster` + `arm_controller`
  (**JointTrajectoryController**，对目标做时间插值 → 平滑运动；早先用 ForwardCommandController
  直发位置会让 GazeboSystem 近乎瞬移、看不清，故改用轨迹控制器)。
- `launch/gazebo.launch.py`：起 gazebo → spawn → 顺序激活两个控制器（`gui:=false` 可无头）。
- `gen_urdf.py`：给夹爪三连杆补了 inertial（Gazebo 需要）。

**已验证（骨架跑通，2026-09-26）**：`xacro`→`check_urdf` 通过；`gazebo.launch.py gui:=false` 起来后
两个控制器 **active**，6 关节 position 命令 + position/velocity/effort 状态接口全部导出；
往 `/arm_controller/joint_trajectory` 发轨迹（或经桥接发边端 joint_command），Gazebo 里臂平滑到位。
用 `ROS_DOMAIN_ID=42` 隔离同机 RViz 会话。

**曾经的坑（已解决）**：`gazebo_ros2_control` 报 "Skipping joint ... not in the gazebo model"、
`list_hardware_interfaces` 为空、控制器激活失败 —— 根因是 **base_link 缺 `<inertial>`**：Gazebo
会丢弃无惯量的连杆，连带其下所有关节都不进模型。`gen_urdf.py` 给 base_link 补了质量/惯量后即解决。

**接边端（已完成，2026-09-26）**：`gazebo_bridge.py` 双向桥接 —— 上行把 ros2_control 的
`/joint_states`（顺序不定）**按关节名重排**成 joint_1..6 发到 `/simulation/{sim_id}/joint_states`
（sensor_msgs/JointState，与 plant_node 同格式）；下行把边端 `/simulation/{sim_id}/joint_command`
（Float64MultiArray）包成 **JointTrajectory（带 `move_time` 时长，默认 2s）**发到
`/arm_controller/joint_trajectory` 驱动 Gazebo，臂按时长平滑到位。已独立验证两向都对
（喂乱序 joint_states→输出正确重排；发 joint_command→控制器命令话题原样收到）。
起法：`ros2 launch gazebo_arm gazebo.launch.py bridge:=true`（默认开）。这样 **Gazebo 物理臂即替换
轻量 plant 接进端边云**：边端 ROS2 模式直接驱动 Gazebo，故障检测/上云链路不变。

> 注：Gazebo GUI 较吃内存，同机若还开着 Docker 云端栈/RViz/浏览器，GUI 可能被系统内存回收
> （非崩溃）。长时间跑建议无头 `gui:=false`，或先腾内存。

**Gazebo 现场（钢材工件，2026-09-26）**：`worlds/steel_yard.world` 把车间搬进 Gazebo 物理世界——
上料输送带、3 根钢管料垛、型钢、钢坯、2 个分拣料框，均为 `static`（布景+碰撞；抓取物理需夹爪驱动，属后续）。
**自带光照+地面**（内联 sun/ground_plane，不用 `model://`，避免离线/代理环境去在线模型库下载卡住——
这正是之前 gzserver 加载卡住的原因）。`gz sdf --check` 通过；launch 默认加载它（`world:=` 可换）。
起法：`ros2 launch gazebo_arm gazebo.launch.py`（默认 steel_yard 世界 + 臂 + 桥接）。

**抓取（运动学吸附，代码完成 / 物理待调，2026-09-26）**：`grasp_node.py` 用「吸附」近似抓取——
订阅 `/gazebo/link_states` 取夹爪(`hydraulic_arm::link_6`，夹爪固定关节被 Gazebo 并入 link_6)位姿，
`/gripper/grasp`(Bool) true 时用 `/gazebo/set_entity_state` 让 `billet` 跟随夹爪(+沿 z 0.16m 偏置)、
false 时释放落下；`billet` 已改为动态模型，世界加了 `libgazebo_ros_state.so`。launch `grasp:=true` 默认起。
- **对齐路点**：需用 Gazebo 真实位姿对齐（我算的 DH FK 与实测不符，且下面的物理不稳导致读数无效）。
- **⚠ 当前阻塞——Gazebo 物理不稳**：实测臂在 JTC/位置接口下近乎运动学 teleport，撞到动态 billet 会把它
  "打飞"(实测 billet 被弹到 (-26,51,7))；加上连杆是真实大质量(link_1=110kg 等)，默认求解器下易发散。
  已给关节加 `<dynamics damping=10 friction=1>`、并把 billet 设为 `kinematic`(免被打飞)。
  **进展**：抓取「拾起+搬运」已跑通——`/gripper/grasp true` 后驱动臂，billet 跟随夹爪抬起(实测 z 0.08→0.64，
  不再打飞)。**未跑通**：干净「释放/放置」——kinematic 体有残余速度、释放后会漂走(实测漂到 z 1.5)；
  需再整定(释放时清零速度/或改动态体自然落下 + 碰撞分类避免接近时碰飞 + effort/PID 替代位置 teleport)。
  这属 README 开头说的"换 Gazebo 需重估动力学/控制器稳定性"，是独立小课题。
- 另注：本机 Gazebo 会话不稳（臂偶发 spawn 不出、CLI 偶发失联、GUI 吃内存被回收），完整实测受限。

## 目录

```
gazebo_arm/
├── gazebo_arm/plant.py        纯 Python 物理 plant + FaultInjector 故障注入(可独立冒烟)
├── gazebo_arm/plant_node.py   ROS2 节点(JointState 发布 / command 订阅 / 场景 / 故障参数)
├── gazebo_arm/scenarios.py    作业场景预设(搬运/喷号/下料分拣的关节路点)
├── gazebo_arm/scene_node.py   现场场景 Marker(地面/料线/钢管/型钢/钢坯/料框/护栏)
├── gazebo_arm/gazebo_bridge.py Gazebo↔边端 桥接(joint_command/joint_states 按名对接)
├── gazebo_arm/grasp_node.py   运动学吸附抓取(工件跟随夹爪/释放落下)
├── gazebo_arm/gen_urdf.py     从孪生 DH/质量生成 URDF(工业臂观感基本体)
├── urdf/hydraulic_arm.urdf    生成产物(RViz/几何)
├── urdf/gazebo_arm.gazebo.xacro  Gazebo 骨架(world+ros2_control+插件)
├── config/arm_controllers.yaml   ros2_control 控制器配置
├── launch/sim_arm.launch.py   RViz 路径：plant + rsp(+RViz)，含 scenario/fault/scene 参数
├── launch/gazebo.launch.py    Gazebo 路径：gazebo + spawn + 控制器
├── package.xml / setup.py     ament_python 包
└── README.md
```
