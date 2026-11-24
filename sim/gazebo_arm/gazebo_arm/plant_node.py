"""ROS2 封装：把 RealtimePlant 接到 ROS2，做「端—边—云」里的实时仿真端。

- 发布 sensor_msgs/JointState 到 /simulation/{sim_id}/joint_states（100Hz，
  position/velocity/effort[6] + header.stamp），供边端订阅。
- 订阅 std_msgs/Float64MultiArray 于 /simulation/{sim_id}/joint_command
  （6 个目标关节角 rad），来自边端下发。

与 edge/edge_node 的 ROS2 契约对齐（见 edge_node/docs/edge_cloud_integration.md）：
边端订阅 joint_states、发布 joint_command，本节点正好互为收发。

注意：本机（Windows）无 ROS2，无法在此运行；在 ros:humble 环境 colcon build 后
`ros2 launch gazebo_arm sim_arm.launch.py` 启动。plant 物理已在 plant.py 独立冒烟验证。
"""
from __future__ import annotations

import re
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray

from gazebo_arm.plant import RealtimePlant, N
from gazebo_arm.scenarios import SCENARIOS

JOINT_NAMES = [f"joint_{i + 1}" for i in range(N)]
HOME = [0.0, 0.35, -0.72, 0.20, 0.0, 0.0]


def _ros2_safe_id(sim_id: str) -> str:
    """把设备标识里 ROS 2 话题名不允许的字符换成 '_'（SIM-001 → SIM_001）。

    ROS 2 话题名只允许字母数字 / '_' / '~' / '{' / '}'，直接拼 'SIM-001' 会被
    rclpy 拒绝（InvalidTopicNameException）。边端（edge_node/config/config_manager.py
    的 render_ros2_topic）用同一规则，两端话题名才能对上。
    """
    return re.sub(r'[^0-9A-Za-z_]', '_', str(sim_id))


class PlantNode(Node):
    def __init__(self):
        super().__init__("gazebo_arm_plant")
        self.declare_parameter("sim_id", "SIM-001")
        self.declare_parameter("rate_hz", 100.0)
        self.declare_parameter("demo", False)      # 无边端时自娱自乐：周期切目标，RViz 能看到臂在动
        # 作业场景：'' / handling(搬运) / marking(喷号) / sorting(下料分拣)——循环下发预设路点
        self.declare_parameter("scenario", "")
        # 故障/扰动注入（默认全关=正常工况），配合边端容错/云端健康分析演示
        self.declare_parameter("fault_sensor_drift", False)
        self.declare_parameter("fault_drift_rate", 0.02)      # rad/s，J1/J2 位置漂移
        self.declare_parameter("fault_actuator_wear", False)
        self.declare_parameter("fault_wear_gain", 0.6)        # J3 出力增益(<1)
        self.declare_parameter("fault_disturbance", False)
        self.declare_parameter("fault_disturbance_torque", 8.0)  # N·m，J2 外扰
        sim_id = self.get_parameter("sim_id").value
        ros_id = _ros2_safe_id(sim_id)
        self.rate_hz = float(self.get_parameter("rate_hz").value)
        self.dt = 1.0 / self.rate_hz

        self.plant = RealtimePlant(HOME)
        self._configure_faults()
        self.pub = self.create_publisher(JointState, f"/simulation/{ros_id}/joint_states", 10)
        self.sub = self.create_subscription(
            Float64MultiArray, f"/simulation/{ros_id}/joint_command", self.on_command, 10)
        self.timer = self.create_timer(self.dt, self.on_tick)
        self._scenario = str(self.get_parameter("scenario").value or "").strip()
        if self._scenario and self._scenario in SCENARIOS:
            self._wp = SCENARIOS[self._scenario]
            self._wp_i = 0
            self._wp_t0 = time.time()
            self.plant.set_target(self._wp[0][1])
            self.create_timer(0.1, self._scenario_tick)
            self.get_logger().info(
                f"作业场景模式 scenario={self._scenario}（{len(self._wp)} 路点循环下发）")
        elif self._scenario:
            self.get_logger().warn(
                f"未知 scenario={self._scenario}，可选 {sorted(SCENARIOS)}；忽略")
        if bool(self.get_parameter("demo").value):
            self._demo_poses = [HOME, [0.5, 0.85, -1.05, 0.45, 0.30, 0.40]]
            self._demo_i = 0
            self.create_timer(4.0, self._demo_tick)   # 每 4s 换个目标
            self.get_logger().info("demo 模式：每 4s 在 home / target 间切换,RViz 可见运动")
        self.get_logger().info(
            f"实时仿真端启动 sim_id={sim_id} rate={self.rate_hz}Hz；"
            f"发布 joint_states / 订阅 joint_command")

    def _configure_faults(self) -> None:
        """按参数配置故障/扰动注入（默认全关）。逐关节只让个别轴劣化，便于观测。"""
        fi = self.plant.faults
        active = []
        if bool(self.get_parameter("fault_sensor_drift").value):
            rate = float(self.get_parameter("fault_drift_rate").value)
            fi.sensor_drift_enabled = True
            fi.sensor_drift_rate = [rate, rate * 0.5, 0.0, 0.0, 0.0, 0.0]  # J1/J2 漂移
            fi.sensor_noise_std = 0.002
            active.append(f"传感器漂移(rate={rate})")
        if bool(self.get_parameter("fault_actuator_wear").value):
            gain = float(self.get_parameter("fault_wear_gain").value)
            fi.actuator_wear_enabled = True
            fi.actuator_gain = [1.0, 1.0, gain, 1.0, 1.0, 1.0]             # J3 出力衰减
            fi.actuator_extra_friction = [0.0, 0.0, 2.0, 0.0, 0.0, 0.0]
            active.append(f"执行器磨损(J3 gain={gain})")
        if bool(self.get_parameter("fault_disturbance").value):
            tq = float(self.get_parameter("fault_disturbance_torque").value)
            fi.disturbance_enabled = True
            fi.disturbance_torque = [0.0, tq, 0.0, 0.0, 0.0, 0.0]          # J2 外扰
            active.append(f"外部扰动(J2 τ={tq}N·m)")
        if active:
            self.get_logger().warn("故障注入已启用：" + "；".join(active))

    def _scenario_tick(self) -> None:
        # 到达当前路点停留时长后切下一个，循环往复
        if time.time() - self._wp_t0 >= self._wp[self._wp_i][2]:
            self._wp_i = (self._wp_i + 1) % len(self._wp)
            self.plant.set_target(self._wp[self._wp_i][1])
            self._wp_t0 = time.time()

    def _demo_tick(self) -> None:
        self._demo_i = 1 - self._demo_i
        self.plant.set_target(self._demo_poses[self._demo_i])

    def on_command(self, msg: Float64MultiArray) -> None:
        data = list(msg.data)
        if len(data) != N:
            self.get_logger().warn(f"joint_command 长度应为 {N}，实际 {len(data)}，忽略")
            return
        try:
            self.plant.set_target(data)
        except ValueError as e:
            self.get_logger().warn(f"joint_command 非法：{e}，忽略")

    def on_tick(self) -> None:
        self.plant.step(self.dt)
        q, qd, tau = self.plant.state()
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = JOINT_NAMES
        msg.position = [float(x) for x in q]
        msg.velocity = [float(x) for x in qd]
        msg.effort = [float(x) for x in tau]
        self.pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = PlantNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
