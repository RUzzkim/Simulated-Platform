#!/bin/bash
# 边端节点容器入口脚本
# - source ROS 2 环境
# - 运行 edge_node 主节点
set -e

# Source ROS 2 + 工作空间
source /opt/ros/humble/setup.bash
source /opt/edge_ws/install/setup.bash

# 配置文件路径（可通过环境变量覆盖）
CONFIG_PATH="${EDGE_CONFIG:-/opt/edge_ws/install/edge_node/share/edge_node/config/edge_config.yaml}"

echo "[entrypoint] 启动边端节点 config=${CONFIG_PATH}"
echo "[entrypoint] simulation_id=${EDGE_SIMULATION_ID:-<from yaml>} broker=${MQTT_BROKER_URL:-<from yaml>}"

# 运行边端主节点（通过 setup.py 注册的 console_scripts 入口）
exec edge_node --config "${CONFIG_PATH}"
