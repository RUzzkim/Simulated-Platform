"""Replay a fixed-step joint state CSV as ROS 2 JointState messages."""

import csv
import math
from pathlib import Path

from .end_effector import JOINT_NAMES


def load_frames(path: Path):
    frames = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            time_s = float(row["sim_time_s"])
            vectors = [
                [float(row[f"{name}_{field}"]) for name in JOINT_NAMES]
                for field in ("position_rad", "velocity_rad_s", "effort_Nm")
            ]
            if not all(math.isfinite(value) for vector in vectors for value in vector):
                raise ValueError("CSV contains a non-finite joint state")
            frames.append((time_s, vectors))

    if len(frames) < 2:
        raise ValueError("CSV must contain at least two frames")
    period = frames[1][0] - frames[0][0]
    if not math.isfinite(period) or period <= 0:
        raise ValueError("CSV timestamps must increase")
    for index, (time_s, _) in enumerate(frames, 1):
        if not math.isclose(time_s, period * index, rel_tol=0, abs_tol=1e-8):
            raise ValueError("CSV timestamps must start at one step and have a fixed interval")
    return period, [vectors for _, vectors in frames]


def main(args=None):
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState

    class ReplayNode(Node):
        def __init__(self):
            super().__init__("joint_state_replay")
            self.declare_parameter("csv_path", "")
            period, self.frames = load_frames(Path(self.get_parameter("csv_path").value))
            self.publisher = self.create_publisher(JointState, "joint_states", 10)
            self.index = 0
            self.timer = self.create_timer(period, self.publish_frame)

        def publish_frame(self):
            if self.index == 0 and self.publisher.get_subscription_count() == 0:
                return
            msg = JointState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.name = list(JOINT_NAMES)
            msg.position, msg.velocity, msg.effort = self.frames[self.index]
            self.publisher.publish(msg)
            self.index += 1
            if self.index == len(self.frames):
                self.timer.cancel()
                self.get_logger().info(f"Replay complete: {self.index} frames")

    rclpy.init(args=args)
    node = None
    try:
        node = ReplayNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
