# 边端节点 Docker 镜像
# 基于 ROS 2 Humble (Ubuntu 22.04 LTS)，包含 rclpy + edge_node 包
#
# 构建:  docker build -t edge_node:latest .
# 运行:  docker run --rm --network host \
#           -e EDGE_SIMULATION_ID=SIM-001 \
#           -e MQTT_BROKER_URL=tcp://<cloud-broker>:1883 \
#           edge_node:latest

FROM ros:humble-ros-base

# 避免交互提示
ENV DEBIAN_FRONTEND=noninteractive

# 系统依赖：pip + 编译工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-colcon-common-extensions \
    ros-humble-ament-python \
    && rm -rf /var/lib/apt/lists/*

# 创建工作空间
RUN mkdir -p /opt/edge_ws/src/edge_node
WORKDIR /opt/edge_ws

# 先复制依赖清单，利用 Docker 缓存层
COPY requirements.txt /opt/edge_ws/src/edge_node/
RUN pip3 install --no-cache-dir -r /opt/edge_ws/src/edge_node/requirements.txt

# 复制边端包源码
COPY edge_node/ /opt/edge_ws/src/edge_node/edge_node/
COPY config/   /opt/edge_ws/src/edge_node/config/
COPY launch/   /opt/edge_ws/src/edge_node/launch/
COPY resource/ /opt/edge_ws/src/edge_node/resource/
COPY package.xml setup.py /opt/edge_ws/src/edge_node/

# 构建 ROS 2 包
RUN /bin/bash -c "source /opt/ros/humble/setup.bash && \
    colcon build --packages-select edge_node --symlink-install"

# 配置文件路径（容器内）
ENV EDGE_CONFIG=/opt/edge_ws/install/edge_node/share/edge_node/config/edge_config.yaml

# 入口脚本：source ROS 2 + 运行边端节点
COPY docker-entrypoint.sh /opt/edge_ws/
RUN chmod +x /opt/edge_ws/docker-entrypoint.sh

ENTRYPOINT ["/opt/edge_ws/docker-entrypoint.sh"]
