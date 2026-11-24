"""ROS 2 状态订阅模块：订阅仿真端的 /simulation/{simulationId}/joint_states"""
from __future__ import annotations

from typing import Callable, Optional

try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    _ROS2_AVAILABLE = True
except ImportError:  # 允许在无 ROS 2 环境下做静态导入与单测
    _ROS2_AVAILABLE = False
    Node = object  # type: ignore


class StateSubscriber:
    """
    订阅 sensor_msgs/JointState，转换为 (position, velocity, effort, stamp_ns) 回调。
    不直接依赖业务层，由 main.py 注入回调完成转换与上传。
    """

    def __init__(self, node, topic: str, callback: Callable):
        if not _ROS2_AVAILABLE:
            raise RuntimeError("rclpy 不可用，无法创建 StateSubscriber")
        self._node = node
        self._callback = callback
        self._subscription = node.create_subscription(
            JointState,
            topic,
            self._on_joint_state,
            10,
        )

    def _on_joint_state(self, msg: 'JointState') -> None:
        try:
            stamp_ns = None
            if msg.header and msg.header.stamp:
                stamp_ns = int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)
            self._callback(
                position=list(msg.position),
                velocity=list(msg.velocity),
                effort=list(msg.effort),
                stamp_ns=stamp_ns,
            )
        except Exception as e:
            self._node.get_logger().error(f"处理 joint_states 失败: {e}")
