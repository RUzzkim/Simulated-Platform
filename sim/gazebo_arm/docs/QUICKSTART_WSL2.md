# 本机 WSL2 跑通端边云 + 看 RViz 动画（一条龙）

目标:在 Windows 本机用 WSL2 把**端 + 边 + 云**跑起来,并在 RViz 里**看到机械臂动**。
分三阶段,每阶段可独立验证,出问题好定位。

> 前提:Windows 11(自带 WSLg,GUI 直接显示);本机内存建议 ≥8G。
> 看动画用**轻量端**(纯数值,不是 Gazebo 3D),RViz 显示骨架运动。

---

## 0. 装 WSL2 + Ubuntu 22.04（一次性）

Windows PowerShell(管理员):

```powershell
wsl --install -d Ubuntu-22.04
```

装完重启、设好用户名密码,进入 Ubuntu。后面命令都在 Ubuntu 里敲。

## 1. 装 ROS2 Humble（native,含 RViz）

Ubuntu 22.04 对应 ROS2 **Humble**(和边端 Docker 同版本)。装 desktop 版(带 RViz):

```bash
sudo apt update && sudo apt install -y software-properties-common curl
sudo add-apt-repository universe -y
# 加 ROS2 apt 源与 key（具体 key 步骤以 docs.ros.org/en/humble 当前页为准）
sudo apt update && sudo apt install -y ros-humble-desktop python3-colcon-common-extensions
echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc && source ~/.bashrc
```

验证:`ros2 --help` 能出来即可。

## 2. 拿到代码 + 建工作空间

```bash
# 把仓库 clone/拷到 WSL2 里(别放 /mnt/c 下,IO 慢;放 ~ 下)
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
ln -s /path/to/platform-cloud/sim/gazebo_arm gazebo_arm      # 或直接拷贝
cd ~/ros2_ws
colcon build --packages-select gazebo_arm
source install/setup.bash
```

## 阶段 1:只起端 + RViz,看动画（最快验证）

```bash
ros2 launch gazebo_arm sim_arm.launch.py rviz:=true demo:=true
```

- `demo:=true`:端每 4s 在 home / target 间来回,**RViz 里能看到臂在动**。
- WSLg 会自动弹出 RViz 窗口(Win11)。看不到窗口就查 WSLg:`wsl --update`。
- 看到臂随 demo 动 → **端 OK**,阶段 1 完成。

## 阶段 2:端 + 边 一起,验证 ROS2 闭环

把边端也 build 进同一工作空间,两个终端分别起端和边:

```bash
cd ~/ros2_ws/src && ln -s /path/to/platform-cloud/edge/edge_node edge_node
cd ~/ros2_ws && pip3 install -r src/edge_node/requirements.txt
colcon build --packages-select gazebo_arm edge_node && source install/setup.bash
```

```bash
# 终端 A：端（不带 demo，由边端驱动）
ros2 launch gazebo_arm sim_arm.launch.py sim_id:=SIM-001 rviz:=true
# 终端 B：边（ROS2 模式，rclpy 可用即自动进）
#   注意：边端启动时会**同步连 MQTT，连不上会直接退出**。阶段 2 还没接云,
#   先起一个本地明文 broker(1883,匿名)给它连,ROS2 收发就能跑起来：
docker run -d --network host --name dummy-mqtt eclipse-mosquitto:2 \
  sh -c "printf 'listener 1883\nallow_anonymous true\n' > /m.conf && exec mosquitto -c /m.conf"
MQTT_BROKER_URL=tcp://localhost:1883 ros2 launch edge_node edge.launch.py
```

验证:

```bash
ros2 topic list | grep simulation             # 应有 joint_states / joint_command
# 手动发个目标，RViz 看臂动 + 边端日志收到状态：
# 注意 ROS 2 话题名不含连字符：SIM-001 → SIM_001（MQTT/云端标识仍是 SIM-001）
ros2 topic pub --once /simulation/SIM_001/joint_command std_msgs/msg/Float64MultiArray \
  "{data: [0.5, 0.85, -1.05, 0.45, 0.30, 0.40]}"
```

臂动 + 边端能收 state、能下发 command → **端↔边 闭环 OK**。

## 阶段 3:边 → 云,看云端页面

云端(backend/mysql/mqtt/nginx)在本机 Docker 已跑着。让边端连本地云 MQTT:

- 连 `ssl://<本地云broker>:8883`(明文 1883 关闭),挂设备证书(CN=SIM-001)+ CA。
- 证书走现成流程:`server/issue-edge-cert.ps1 -DeviceCode SIM-001`,把
  `edge-SIM-001.{crt,key}` + `ca.crt` 挂进边端,`MQTT_BROKER_URL` 指向本地 broker。
- 详见 `edge/edge_node/docs/edge_cloud_integration.md` 的 mTLS 对接。

验证:云端页面(`https://127.0.0.1:8443`)设备 `SIM-001` 出现遥测/振动曲线;
`/api/analysis/devices/{id}/trend?metric=vibration` 出趋势 → **端→边→云 全通**。

---

## 常见坑

### 阶段 1 跑不起来的对照排查

| 现象 | 原因 / 解决 |
|---|---|
| `package 'gazebo_arm' not found` | 没 `source ~/ros2_ws/install/setup.bash`(每个新终端都要) |
| `executable 'plant_node' not found` | `colcon build` 没成功或没 source;重 build 再 source |
| colcon 报缺 `robot_state_publisher` | `sudo apt install ros-humble-robot-state-publisher`(desktop 版已含) |
| RViz 窗口不弹 | Win11 才有 WSLg;`wsl --update` 后重开;`echo $DISPLAY` 应非空 |
| RViz 开了但**看不到臂** | RobotModel 的 Description Topic 设为 `/robot_description`;Fixed Frame 设 `base_link`(配置里已设好,若手改过就改回) |
| 臂在但**不动** | 确认带了 `demo:=true`;`ros2 topic echo /simulation/SIM_001/joint_states --once` 看 position 是否在变 |
| 臂是一串圆柱、姿势怪 | 正常:URDF 几何用 DH 近似,只为看运动,不是精确外形 |
| `ros2 topic list` 能看到话题但 `echo` 收不到数据（Docker 多容器） | 两容器没共享 `/dev/shm`,FastDDS 默认走共享内存传输、跨容器不通;`docker-compose.yml` 里两个服务都要 `ipc: host`（已配好） |

> 已验证:demo 模式驱动臂在 home↔target 间摆动约 **0.5 rad(~29°)**,只要 RViz 显示出模型,就一定看得到它动。

- **代码放 `~` 下,别放 `/mnt/c`**:WSL2 跨盘 IO 慢,colcon build 会很慢。
- **端和边同一 `ROS_DOMAIN_ID`**(默认 0)且同主机,DDS 才能互相发现。
- **RViz 不弹窗**:Win11 才有 WSLg;先 `wsl --update`。臂显示为一串圆柱是正常的
  (URDF 几何用 DH 近似,见 `README.md`)。
- **看动画只在本机**;部署到服务器是 headless,服务器看云端网页数据。
- **边端启动必须能连上 MQTT broker,否则直接退出**:阶段 1(只起端)不用 MQTT;
  阶段 2 起边端就得有个 broker——没接云时用上面的本地明文 broker 顶上,阶段 3 换成云端 broker。
