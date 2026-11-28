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
from launch_ros.parameter_descriptions import ParameterValue
from gazebo_arm.plant import JOINT_LOCK_MODE_CONFLICT


def _ros2_safe_id(sim_id: str) -> str:
    return re.sub(r'[^0-9A-Za-z_]', '_', str(sim_id))


def _launch_setup(context, *args, **kwargs):
    if (LaunchConfiguration("fault_lock_joint").perform(context)
            and IfCondition(LaunchConfiguration("fault_joint_lock")).evaluate(context)):
        raise ValueError(JOINT_LOCK_MODE_CONFLICT)

    share = get_package_share_directory("gazebo_arm")
    urdf = os.path.join(share, "urdf", "hydraulic_arm.urdf")
    rviz_cfg = os.path.join(share, "rviz", "arm.rviz")
    with open(urdf, "r", encoding="utf-8") as f:
        robot_description = f.read()

    sim_id = LaunchConfiguration("sim_id").perform(context)
    ros_id = _ros2_safe_id(sim_id)
    rviz = LaunchConfiguration("rviz")
    replay_csv = LaunchConfiguration("replay_csv").perform(context)
    state_topic = f"/simulation/{ros_id}/joint_states"
    trajectory_topic = f"/simulation/{ros_id}/arm_trajectory"
    has_scenario = bool(LaunchConfiguration("scenario").perform(context).strip())
    demo_enabled = IfCondition(LaunchConfiguration("demo")).evaluate(context)

    source = (
        Node(
            package="gazebo_arm", executable="replay_joint_states",
            parameters=[{"csv_path": replay_csv}],
            remappings=[("joint_states", state_topic)],
            output="screen",
        ) if replay_csv else
        Node(
            package="gazebo_arm", executable="plant_node", name="gazebo_arm_plant",
            parameters=[{"sim_id": sim_id, "rate_hz": 100.0,
                         "demo": LaunchConfiguration("demo"),
                         "scenario": LaunchConfiguration("scenario"),
                         "scenario_loop": ParameterValue(LaunchConfiguration("scenario_loop"), value_type=bool),
                         "fault_sensor_drift": LaunchConfiguration("fault_sensor_drift"),
                         "fault_actuator_wear": LaunchConfiguration("fault_actuator_wear"),
                         "fault_disturbance": LaunchConfiguration("fault_disturbance"),
                         "fault_lock_joint": ParameterValue(LaunchConfiguration("fault_lock_joint"), value_type=str),
                         "fault_lock_at": ParameterValue(LaunchConfiguration("fault_lock_at"), value_type=float),
                         "fault_joint_lock": ParameterValue(
                             LaunchConfiguration("fault_joint_lock"), value_type=bool),
                         "fault_joint_lock_index": ParameterValue(
                             LaunchConfiguration("fault_joint_lock_index"), value_type=int),
                         "fault_joint_lock_onset_s": ParameterValue(
                             LaunchConfiguration("fault_joint_lock_onset_s"), value_type=float),
                         "fault_joint_lock_after_first_command": ParameterValue(
                             LaunchConfiguration("fault_joint_lock_after_first_command"), value_type=bool),
                         "fault_joint_lock_reaction_torque": ParameterValue(
                             LaunchConfiguration("fault_joint_lock_reaction_torque"), value_type=float),
                         "initial_joint_positions": ParameterValue(
                             LaunchConfiguration("initial_joint_positions"), value_type=str)}],
            output="screen",
        )
    )
    return [
        source,
        Node(
            package="robot_state_publisher", executable="robot_state_publisher",
            name="robot_state_publisher",
            parameters=[{"robot_description": robot_description},
                        {"publish_frequency": 100.0 if replay_csv else 50.0}],
            remappings=[("/joint_states", state_topic)],
            output="screen",
        ),
        Node(
            package="rviz2", executable="rviz2", name="rviz2",
            arguments=["-d", rviz_cfg],
            remappings=[("/arm_trajectory", trajectory_topic)],
            condition=IfCondition(rviz), output="screen",
        ),
        Node(
            package="gazebo_arm", executable="control_panel",
            parameters=[{"read_only": bool(replay_csv) or has_scenario or demo_enabled}],
            remappings=[("joint_states", state_topic),
                        ("joint_command", f"/simulation/{ros_id}/joint_command"),
                        ("arm_trajectory", trajectory_topic)],
            condition=IfCondition(LaunchConfiguration("panel")), output="screen",
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
        DeclareLaunchArgument("panel", default_value="false"),
        DeclareLaunchArgument("demo", default_value="false"),
        DeclareLaunchArgument("replay_csv", default_value=""),
        # 作业场景：handling(搬运)/marking(喷号)/sorting(下料分拣)，空=由边端驱动
        DeclareLaunchArgument("scenario", default_value=""),
        DeclareLaunchArgument("scenario_loop", default_value="true"),
        # 故障/扰动注入（默认全关），配合边端容错 / 云端健康分析演示
        DeclareLaunchArgument("fault_sensor_drift", default_value="false"),
        DeclareLaunchArgument("fault_actuator_wear", default_value="false"),
        DeclareLaunchArgument("fault_disturbance", default_value="false"),
        DeclareLaunchArgument("fault_lock_joint", default_value=""),
        DeclareLaunchArgument("fault_lock_at", default_value="0.30"),
        DeclareLaunchArgument("fault_joint_lock", default_value="false"),
        DeclareLaunchArgument("fault_joint_lock_index", default_value="2"),
        DeclareLaunchArgument("fault_joint_lock_onset_s", default_value="5.0"),
        DeclareLaunchArgument("fault_joint_lock_after_first_command", default_value="false"),
        DeclareLaunchArgument("fault_joint_lock_reaction_torque", default_value="12.5"),
        DeclareLaunchArgument("initial_joint_positions", default_value="0.0,0.35,-0.72,0.20,0.0,0.0"),
        # 现场场景：地面/料线/钢管/型钢/钢坯/料框（Marker）
        DeclareLaunchArgument("scene", default_value="true"),
        OpaqueFunction(function=_launch_setup),
    ])
