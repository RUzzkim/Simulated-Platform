#!/bin/bash
# 入口：source ROS 2 + 本包，起实时仿真端（plant + robot_state_publisher，无 RViz）
set -e
source /opt/ros/humble/setup.bash
source /opt/sim_ws/install/setup.bash
exec ros2 launch gazebo_arm sim_arm.launch.py \
    sim_id:="${EDGE_SIMULATION_ID:-SIM-001}" rviz:=false
