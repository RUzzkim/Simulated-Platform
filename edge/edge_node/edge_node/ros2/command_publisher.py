"""ROS 2 控制指令发布模块：向仿真端发布 /simulation/{simulationId}/joint_command"""
from __future__ import annotations

from typing import List, Optional

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import Float64MultiArray
    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    Node = object  # type: ignore


class CommandPublisher:
    """
    发布目标关节位置到 joint_command topic。
    phase1 使用 std_msgs/Float64MultiArray（6 个目标角度，rad）。
    待确认：仿真端是否需要自定义消息（含 commandType/targetVelocity/targetTorque）。
    """

    def __init__(self, node, topic: str):
        if not _ROS2_AVAILABLE:
            raise RuntimeError("rclpy 不可用，无法创建 CommandPublisher")
        self._node = node
        self._publisher = node.create_publisher(Float64MultiArray, topic, 10)

    def publish_position(self, target: List[float]) -> None:
        msg = Float64MultiArray()
        msg.data = [float(x) for x in target]
        self._publisher.publish(msg)
        self._node.get_logger().debug(f"发布 joint_command target={target}")
