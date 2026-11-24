"""Gazebo ↔ 边端 桥接：让 Gazebo 物理臂替换轻量 plant，接进端边云闭环。

- 上行：订阅 ros2_control 的 /joint_states（joint_state_broadcaster 发布，顺序不定）
  → 按 joint_1..6 重排 → 发布 sensor_msgs/JointState 到 /simulation/{sim_id}/joint_states，
  供边端订阅（与 plant_node 输出同格式）。
- 下行：订阅边端 /simulation/{sim_id}/joint_command（std_msgs/Float64MultiArray，6 目标角）
  → 包成 trajectory_msgs/JointTrajectory（带 move_time 时长）发到 /arm_controller/joint_trajectory，
  由 JointTrajectoryController 插值 → 关节按时长平滑到位（不再瞬移）。

注意：joint_state_broadcaster 的 position 数组顺序 ≠ joint_1..6，必须按 name 映射（否则关节错位）。

    ros2 run gazebo_arm gazebo_bridge --ros-args -p sim_id:=SIM-001 -p move_time:=2.0
"""
from __future__ import annotations

import re

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

N = 6
JOINT_NAMES = [f"joint_{i + 1}" for i in range(N)]


def _ros2_safe_id(sim_id: str) -> str:
    return re.sub(r'[^0-9A-Za-z_]', '_', str(sim_id))


class GazeboBridge(Node):
    def __init__(self):
        super().__init__("gazebo_bridge")
        self.declare_parameter("sim_id", "SIM-001")
        self.declare_parameter("command_topic", "/arm_controller/joint_trajectory")
        self.declare_parameter("move_time", 2.0)   # 每个目标插值到位的时长(秒)，越大越慢越好看
        ros_id = _ros2_safe_id(self.get_parameter("sim_id").value)
        cmd_topic = self.get_parameter("command_topic").value
        self._move_time = float(self.get_parameter("move_time").value)

        # 上行：Gazebo /joint_states → 边端 joint_states（按名重排）
        self.state_pub = self.create_publisher(
            JointState, f"/simulation/{ros_id}/joint_states", 10)
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 10)
        # 下行：边端 joint_command → JointTrajectory（平滑插值）
        self.cmd_pub = self.create_publisher(JointTrajectory, cmd_topic, 10)
        self.create_subscription(
            Float64MultiArray, f"/simulation/{ros_id}/joint_command", self._on_command, 10)

        self._warned = False
        self.get_logger().info(
            f"Gazebo 桥接启动 sim_id={ros_id}：/joint_states→joint_states(按名重排)，"
            f"joint_command→{cmd_topic}(轨迹插值 {self._move_time}s)")

    def _on_joint_states(self, msg: JointState):
        # 按 joint_1..6 顺序取值，缺失关节跳过
        idx = {name: i for i, name in enumerate(msg.name)}
        if not all(n in idx for n in JOINT_NAMES):
            if not self._warned:
                self.get_logger().warn(f"/joint_states 缺关节，收到 {list(msg.name)}")
                self._warned = True
            return
        out = JointState()
        out.header = msg.header
        out.name = list(JOINT_NAMES)
        pos, vel, eff = list(msg.position), list(msg.velocity), list(msg.effort)
        out.position = [pos[idx[n]] for n in JOINT_NAMES] if pos else []
        out.velocity = [vel[idx[n]] for n in JOINT_NAMES] if vel else []
        out.effort = [eff[idx[n]] for n in JOINT_NAMES] if eff else []
        self.state_pub.publish(out)

    def _on_command(self, msg: Float64MultiArray):
        data = list(msg.data)
        if len(data) != N:
            self.get_logger().warn(f"joint_command 长度应为 {N}，实际 {len(data)}，忽略")
            return
        traj = JointTrajectory()
        traj.joint_names = list(JOINT_NAMES)
        pt = JointTrajectoryPoint()
        pt.positions = [float(x) for x in data]
        sec = int(self._move_time)
        pt.time_from_start.sec = sec
        pt.time_from_start.nanosec = int((self._move_time - sec) * 1e9)
        traj.points = [pt]
        self.cmd_pub.publish(traj)


def main(args=None):
    rclpy.init(args=args)
    node = GazeboBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
