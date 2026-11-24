"""运动学吸附抓取：让工件在"抓取"时跟随夹爪、"释放"时落下，实现 pick-and-place。

Gazebo Classic 里真·摩擦夹持不稳，工业仿真常用"吸附"近似：抓取时用 set_entity_state
让目标工件的位姿跟随夹爪 link（+沿夹爪 z 的偏置），释放时停止跟随、工件回归物理（落下）。

- 读夹爪位姿：订阅 /gazebo/link_states（gazebo_ros_state 插件发布），取 gripper_link。
- 写工件位姿：调用 /gazebo/set_entity_state。
- 抓/放开关：订阅 /gripper/grasp（std_msgs/Bool，true=吸附，false=释放）。

    ros2 run gazebo_arm grasp_node --ros-args -p target_model:=billet
需世界加载 libgazebo_ros_state.so（steel_yard.world 已加）。工件须为非 static 模型。
"""
from __future__ import annotations

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from gazebo_msgs.msg import LinkStates
from gazebo_msgs.srv import SetEntityState


class GraspNode(Node):
    def __init__(self):
        super().__init__("grasp_node")
        self.declare_parameter("target_model", "billet")
        # 夹爪固定关节在 Gazebo 里被并入 link_6（fixed-joint lumping），故取 link_6 + 沿其 z 偏置到指尖
        self.declare_parameter("gripper_link", "hydraulic_arm::link_6")
        self.declare_parameter("grip_offset", 0.16)   # 沿夹爪 z 的偏置(m)，让工件贴在指间
        self.declare_parameter("rate", 20.0)
        self.target = self.get_parameter("target_model").value
        self.gripper_link = self.get_parameter("gripper_link").value
        self.offset = float(self.get_parameter("grip_offset").value)

        self._grasping = False
        self._grip_pose = None   # (px,py,pz, qx,qy,qz,qw)
        self._held = None        # 释放后固定工件在此位姿（持续下发，防 kinematic 体残留速度漂走）

        self.create_subscription(Bool, "/gripper/grasp", self._on_grasp, 10)
        self.create_subscription(LinkStates, "/gazebo/link_states", self._on_links, 10)
        self.cli = self.create_client(SetEntityState, "/gazebo/set_entity_state")
        rate = float(self.get_parameter("rate").value)
        self.create_timer(1.0 / rate, self._tick)
        self.get_logger().info(
            f"抓取节点启动：target={self.target} gripper={self.gripper_link} "
            f"offset={self.offset}m；/gripper/grasp true=吸附 false=释放")

    def _on_grasp(self, msg: Bool):
        if msg.data != self._grasping:
            self.get_logger().info("抓取" if msg.data else "释放")
        self._grasping = msg.data

    def _on_links(self, msg: LinkStates):
        try:
            i = msg.name.index(self.gripper_link)
        except ValueError:
            return
        p = msg.pose[i]
        self._grip_pose = (p.position.x, p.position.y, p.position.z,
                           p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w)

    def _set_pose(self, x, y, z, qx, qy, qz, qw):
        if not self.cli.service_is_ready():
            return
        req = SetEntityState.Request()
        req.state.name = self.target
        req.state.reference_frame = "world"
        req.state.pose.position.x = x
        req.state.pose.position.y = y
        req.state.pose.position.z = z
        req.state.pose.orientation.x = qx
        req.state.pose.orientation.y = qy
        req.state.pose.orientation.z = qz
        req.state.pose.orientation.w = qw
        # twist 全 0：避免 kinematic 体累积速度、释放后飘走
        self.cli.call_async(req)

    def _tick(self):
        if self._grasping and self._grip_pose is not None:
            px, py, pz, qx, qy, qz, qw = self._grip_pose
            # 夹爪局部 z 轴在世界系方向 × offset（旋转矩阵第三列）
            ox = 2.0 * (qx * qz + qw * qy) * self.offset
            oy = 2.0 * (qy * qz - qw * qx) * self.offset
            oz = (1.0 - 2.0 * (qx * qx + qy * qy)) * self.offset
            self._held = (px + ox, py + oy, pz + oz, qx, qy, qz, qw)
            self._set_pose(*self._held)
        elif self._held is not None:
            # 释放后持续钉在最后位姿，防止 kinematic 体带残余速度漂走
            self._set_pose(*self._held)


def main(args=None):
    rclpy.init(args=args)
    node = GraspNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
