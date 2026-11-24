"""现场场景可视化：发布 visualization_msgs/MarkerArray，在 RViz 里画出钢铁后处理车间——
地面、上料输送带、钢管料垛、型钢、钢坯、分拣料框、安全护栏，把机械臂放进"现场"里。

与机器人 URDF 解耦：场景走 Marker（/scene 话题），不动 robot_description。
坐标系 base_link（RViz Fixed Frame），工件摆在机械臂可达范围(~0.5–0.9m)内。

    ros2 run gazebo_arm scene_node
"""
from __future__ import annotations

import math

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from visualization_msgs.msg import Marker, MarkerArray

FRAME = "base_link"


def _quat(axis: str):
    # 圆柱默认沿 z；'x'/'y' 让其躺倒沿该轴
    h = math.sqrt(0.5)
    if axis == "x":
        return (h, 0.0, 0.0, h)
    if axis == "y":
        return (0.0, h, 0.0, h)
    return (0.0, 0.0, 0.0, 1.0)


# (类型, 命名, xyz, 轴, scale xyz, rgba) —— 一个简洁但可辨认的钢铁车间现场
SCENE = [
    ("cube", "floor",     (0.0, 0.0, -0.012), "z", (4.0, 4.0, 0.02), (0.30, 0.30, 0.33, 1.0)),
    # 上料输送带（右前，+x）
    ("cube", "conveyor",  (0.85, 0.30, 0.06), "z", (0.45, 1.30, 0.12), (0.18, 0.18, 0.20, 1.0)),
    # 钢管料垛（躺在料线上，沿 y）
    ("cyl",  "pipe",      (0.80, 0.15, 0.16), "y", (0.10, 0.10, 0.70), (0.62, 0.64, 0.68, 1.0)),
    ("cyl",  "pipe",      (0.80, 0.30, 0.16), "y", (0.10, 0.10, 0.70), (0.60, 0.50, 0.40, 1.0)),
    ("cyl",  "pipe",      (0.86, 0.22, 0.25), "y", (0.10, 0.10, 0.70), (0.62, 0.64, 0.68, 1.0)),
    # 型钢（H 型钢近似为方料）
    ("cube", "beam",      (0.55, 0.55, 0.06), "z", (0.55, 0.10, 0.10), (0.55, 0.57, 0.60, 1.0)),
    # 钢坯（喷号对象，暖色调）
    ("cube", "billet",    (0.55, 0.02, 0.10), "z", (0.26, 0.26, 0.20), (0.55, 0.33, 0.22, 1.0)),
    # 分拣料框（黄色，左侧/后侧）
    ("cube", "bin_a",     (0.30, -0.60, 0.10), "z", (0.35, 0.35, 0.20), (0.85, 0.72, 0.15, 1.0)),
    ("cube", "bin_b",     (-0.55, -0.35, 0.10), "z", (0.35, 0.35, 0.20), (0.85, 0.72, 0.15, 1.0)),
    ("cube", "bin_c",     (-0.55, 0.35, 0.10), "z", (0.35, 0.35, 0.20), (0.85, 0.72, 0.15, 1.0)),
]


class SceneNode(Node):
    def __init__(self):
        super().__init__("gazebo_arm_scene")
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub = self.create_publisher(MarkerArray, "/scene", qos)
        self.timer = self.create_timer(2.0, self._publish)   # 周期重发，晚到的 RViz 也能收到
        self._publish()
        self.get_logger().info("现场场景已发布到 /scene（地面/料线/钢管/型钢/钢坯/料框）")

    def _publish(self):
        arr = MarkerArray()
        for i, (kind, ns, xyz, axis, scale, rgba) in enumerate(SCENE):
            mk = self._marker(i, kind, ns, xyz, axis, scale, rgba)
            arr.markers.append(mk)
        # 安全护栏：一圈立柱
        for j in range(8):
            ang = j * math.pi / 4
            x, y = 1.4 * math.cos(ang), 1.4 * math.sin(ang)
            arr.markers.append(self._marker(
                100 + j, "cyl", "fence", (x, y, 0.35), "z",
                (0.05, 0.05, 0.7), (0.90, 0.55, 0.10, 1.0)))
        self.pub.publish(arr)

    def _marker(self, mid, kind, ns, xyz, axis, scale, rgba):
        mk = Marker()
        mk.header.frame_id = FRAME
        mk.header.stamp = self.get_clock().now().to_msg()
        mk.ns = ns
        mk.id = mid
        mk.type = Marker.CYLINDER if kind == "cyl" else Marker.CUBE
        mk.action = Marker.ADD
        mk.pose.position.x, mk.pose.position.y, mk.pose.position.z = xyz
        q = _quat(axis)
        mk.pose.orientation.x, mk.pose.orientation.y, mk.pose.orientation.z, mk.pose.orientation.w = q
        mk.scale.x, mk.scale.y, mk.scale.z = scale
        mk.color.r, mk.color.g, mk.color.b, mk.color.a = rgba
        return mk


def main(args=None):
    rclpy.init(args=args)
    node = SceneNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
