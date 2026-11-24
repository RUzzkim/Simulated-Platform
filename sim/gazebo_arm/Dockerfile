# 轻量实时仿真端（gazebo_arm）Docker 镜像
# 基于 ROS 2 Humble（与边端 edge_node 同款），只跑 plant + robot_state_publisher（无界面）。
#
# 构建: docker build -t gazebo_arm:latest .
# 运行: docker run --rm --network host -e EDGE_SIMULATION_ID=SIM-001 gazebo_arm:latest
FROM ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive

# [本机构建环境专用] apt 走清华镜像：本机代理对 archive.ubuntu.com / packages.ros.org
# 返回 502 Bad Gateway，改用可达镜像；ros2 源去掉 deb-src（该镜像不提供 Sources）。
# 与代码逻辑无关，换网络环境可删。
RUN sed -i 's|http://archive.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g; s|http://security.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' /etc/apt/sources.list \
    && sed -i 's|http://packages.ros.org/ros2/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu|g; s|^Types: deb deb-src|Types: deb|g' /etc/apt/sources.list.d/ros2.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-colcon-common-extensions \
    ros-humble-robot-state-publisher \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/sim_ws/src/gazebo_arm
WORKDIR /opt/sim_ws

# 复制包源码（不含 gen_urdf 的孪生依赖：urdf 已预生成随包带走）
COPY gazebo_arm/ /opt/sim_ws/src/gazebo_arm/gazebo_arm/
COPY launch/   /opt/sim_ws/src/gazebo_arm/launch/
COPY urdf/     /opt/sim_ws/src/gazebo_arm/urdf/
COPY rviz/     /opt/sim_ws/src/gazebo_arm/rviz/
COPY resource/ /opt/sim_ws/src/gazebo_arm/resource/
COPY package.xml setup.py setup.cfg /opt/sim_ws/src/gazebo_arm/

RUN /bin/bash -c "source /opt/ros/humble/setup.bash && \
    colcon build --packages-select gazebo_arm --symlink-install"

COPY docker-entrypoint.sh /opt/sim_ws/
RUN chmod +x /opt/sim_ws/docker-entrypoint.sh

ENTRYPOINT ["/opt/sim_ws/docker-entrypoint.sh"]
