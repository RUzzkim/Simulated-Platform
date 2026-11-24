"""Gazebo 骨架 launch：起 Gazebo + spawn 机械臂 + 加载 ros2_control 控制器。

    ros2 launch gazebo_arm gazebo.launch.py

流程：xacro 生成 robot_description → 起 gazebo(gzserver+gzclient) → robot_state_publisher
→ spawn_entity 把臂放进 Gazebo → 依次激活 joint_state_broadcaster、arm_position_controller。

驱动：往 /arm_position_controller/commands 发 std_msgs/Float64MultiArray（6 关节位置）即可让臂动；
状态从 /joint_states 出。接边端（joint_command/joint_states）用 gazebo_bridge.py 桥接，见 README。
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            RegisterEventHandler)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory("gazebo_arm")
    xacro_file = os.path.join(pkg, "urdf", "gazebo_arm.gazebo.xacro")
    world_file = os.path.join(pkg, "worlds", "steel_yard.world")
    robot_description = {"robot_description": Command(["xacro ", xacro_file])}
    gui = LaunchConfiguration("gui")

    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory("gazebo_ros"), "launch", "gazebo.launch.py")),
        launch_arguments={"gui": gui, "world": LaunchConfiguration("world"),
                          "verbose": "false"}.items(),
    )

    rsp = Node(
        package="robot_state_publisher", executable="robot_state_publisher",
        output="screen",
        parameters=[robot_description, {"use_sim_time": True}],
    )
    spawn = Node(
        package="gazebo_ros", executable="spawn_entity.py",
        arguments=["-topic", "robot_description", "-entity", "hydraulic_arm"],
        output="screen",
    )
    jsb = Node(package="controller_manager", executable="spawner",
               arguments=["joint_state_broadcaster"], output="screen")
    arm_ctrl = Node(package="controller_manager", executable="spawner",
                    arguments=["arm_controller"], output="screen")
    # 桥接：把 Gazebo 接进端边云（边端 joint_command/joint_states 对接）
    bridge = Node(
        package="gazebo_arm", executable="gazebo_bridge", name="gazebo_bridge",
        parameters=[{"sim_id": LaunchConfiguration("sim_id")}],
        condition=IfCondition(LaunchConfiguration("bridge")), output="screen",
    )
    # 运动学吸附抓取节点（/gripper/grasp 控制 pick/place）
    grasp = Node(
        package="gazebo_arm", executable="grasp_node", name="grasp_node",
        condition=IfCondition(LaunchConfiguration("grasp")), output="screen",
    )

    return LaunchDescription([
        DeclareLaunchArgument("gui", default_value="true", description="是否起 Gazebo 客户端窗口"),
        DeclareLaunchArgument("world", default_value=world_file, description="Gazebo 世界文件(默认钢铁车间)"),
        DeclareLaunchArgument("sim_id", default_value="SIM-001", description="仿真设备号"),
        DeclareLaunchArgument("bridge", default_value="true", description="是否起边端桥接"),
        DeclareLaunchArgument("grasp", default_value="true", description="是否起运动学吸附抓取"),
        gazebo,
        rsp,
        spawn,
        bridge,
        grasp,
        # spawn 完成后再激活控制器，顺序：broadcaster -> position controller
        RegisterEventHandler(OnProcessExit(target_action=spawn, on_exit=[jsb])),
        RegisterEventHandler(OnProcessExit(target_action=jsb, on_exit=[arm_ctrl])),
    ])
