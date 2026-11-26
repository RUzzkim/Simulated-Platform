#!/bin/bash
# 入口：source ROS 2 + 本包，起实时仿真端（plant + robot_state_publisher，无 RViz）
set -e
source /opt/ros/humble/setup.bash
source /opt/sim_ws/install/setup.bash
exec ros2 launch gazebo_arm sim_arm.launch.py \
    sim_id:="${EDGE_SIMULATION_ID:-SIM-001}" rviz:=false \
    fault_joint_lock:="${SIM_FAULT_JOINT_LOCK:-true}" \
    fault_joint_lock_index:="${SIM_FAULT_JOINT_LOCK_INDEX:-2}" \
    fault_joint_lock_onset_s:="${SIM_FAULT_JOINT_LOCK_ONSET_S:-1.0}" \
    fault_joint_lock_after_first_command:="${SIM_FAULT_JOINT_LOCK_AFTER_FIRST_COMMAND:-true}" \
    fault_joint_lock_reaction_torque:="${SIM_FAULT_JOINT_LOCK_REACTION_TORQUE:-12.5}" \
    initial_joint_positions:="${SIM_INITIAL_JOINT_POSITIONS:-0.0,0.35,-0.72,0.2,0.0,0.0}"
