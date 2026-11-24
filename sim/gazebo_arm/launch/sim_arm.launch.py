"""启动轻量实时仿真端：plant 节点 + robot_state_publisher(+可选 RViz)。

    ros2 launch gazebo_arm sim_arm.launch.py sim_id:=SIM-001 rviz:=true

plant 节点发布 /simulation/<sim_id>/joint_states、订阅 .../joint_command；
robot_state_publisher 用 URDF 把 JointState 转成 TF 供 RViz/Gazebo 可视化。

注意：ROS 2 话题名不允许连字符，设备标识 SIM-001 会被拒（InvalidTopicNameException），
所以话题段用 _ros2_safe_id 把非法字符换成 '_'（SIM-001 → SIM_001）；plant_node 与
边端 config_manager.render_ros2_topic 用同一规则，三方话题名才能对上。
"""
import os
import re

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _ros2_safe_id(sim_id: str) -> str:
    return re.sub(r'[^0-9A-Za-z_]', '_', str(sim_id))


def _launch_setup(context, *args, **kwargs):
    share = get_package_share_directory("gazebo_arm")
    urdf = os.path.join(share, "urdf", "hydraulic_arm.urdf")
    rviz_cfg = os.path.join(share, "rviz", "arm.rviz")
    with open(urdf, "r", encoding="utf-8") as f:
        robot_description = f.read()

    sim_id = LaunchConfiguration("sim_id").perform(context)
    ros_id = _ros2_safe_id(sim_id)
    rviz = LaunchConfiguration("rviz")

    return [
        Node(
            package="gazebo_arm", executable="plant_node", name="gazebo_arm_plant",
            parameters=[{"sim_id": sim_id, "rate_hz": 100.0,
                         "demo": LaunchConfiguration("demo"),
                         "scenario": LaunchConfiguration("scenario"),
                         "fault_sensor_drift": LaunchConfiguration("fault_sensor_drift"),
                         "fault_actuator_wear": LaunchConfiguration("fault_actuator_wear"),
                         "fault_disturbance": LaunchConfiguration("fault_disturbance")}],
            output="screen",
        ),
        Node(
            package="robot_state_publisher", executable="robot_state_publisher",
            name="robot_state_publisher",
            parameters=[{"robot_description": robot_description}],
            remappings=[("/joint_states", f"/simulation/{ros_id}/joint_states")],
            output="screen",
        ),
        Node(
            package="rviz2", executable="rviz2", name="rviz2",
            arguments=["-d", rviz_cfg],
            condition=IfCondition(rviz), output="screen",
        ),
        Node(
            package="gazebo_arm", executable="scene_node", name="gazebo_arm_scene",
            condition=IfCondition(LaunchConfiguration("scene")), output="screen",
        ),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("sim_id", default_value="SIM-001"),
        DeclareLaunchArgument("rviz", default_value="false"),
        DeclareLaunchArgument("demo", default_value="false"),
        # 作业场景：handling(搬运)/marking(喷号)/sorting(下料分拣)，空=由边端驱动
        DeclareLaunchArgument("scenario", default_value=""),
        # 故障/扰动注入（默认全关），配合边端容错 / 云端健康分析演示
        DeclareLaunchArgument("fault_sensor_drift", default_value="false"),
        DeclareLaunchArgument("fault_actuator_wear", default_value="false"),
        DeclareLaunchArgument("fault_disturbance", default_value="false"),
        # 现场场景：地面/料线/钢管/型钢/钢坯/料框（Marker）
        DeclareLaunchArgument("scene", default_value="true"),
        OpaqueFunction(function=_launch_setup),
    ])
