# 服务器检查记录

状态：已完成

## 执行日期

- 2026-09-18（服务器输出由用户提供）

## 服务器信息

- 主机名：iZuf61hcwb5j4coxdfdfncZ
- 操作系统：Ubuntu（内核 5.15.0-187-generic）
- vCPU：未采集（服务器规格标称 2 核）
- 内存：总计 3.4 GiB，已用 1.2 GiB，可用约 1.9 GiB，无 Swap
- 磁盘：根分区 59G，已用 8.4G，可用 48G
- Docker：29.7.2
- Docker Compose：v5.5.0

## MQTT Broker 检查

- EMQX：未安装
- 宿主机 Mosquitto：未安装
- 容器化 Mosquitto：`robot-mosquitto`（eclipse-mosquitto:2）已运行 5 小时，监听 `127.0.0.1:1883`
- 决策：继续使用容器化 Mosquitto，暂不启用 8883/TLS，后续边缘端公网接入时再开启

## 端口占用检查

- 80：被 `xinqing-frontend` 容器占用
- 1883：被 `robot-mosquitto` 占用，仅绑定本机回环
- 443、8883、3306、8080：未发现宿主机监听
- 8081：被 `tobebetter` 容器占用

## 现有容器

- `xinqing-mysql`（mysql:8.0）：健康运行，未映射宿主机 3306
- `xinqing-backend`（xinqing-backend:1.0）：运行中，仅容器网络 8080
- `xinqing-frontend`（xinqing-frontend:1.0）：运行中，占用宿主机 80
- `tobebetter`（tobebetter:1.0）：健康运行，占用宿主机 8081

## 资源限制方案

- MySQL：复用现有 `xinqing-mysql`，不在本项目 compose 中重复部署
- Mosquitto：继续运行 `robot-mosquitto`，内存限制 256M
- Spring Boot：`-Xms256m -Xmx512m`，容器限制 768M
- Nginx：容器内存限制 128M，但端口 80 已被占用，需改端口或合并入口

## 结论

- Docker 环境满足部署要求。
- 服务器内存偏紧且无 Swap，需保持逐个服务启动和验证。
- MySQL 复用 `xinqing-mysql`。
- Broker 复用已运行的 `robot-mosquitto`。
- 端口 80 已被现有业务占用，本项目 Nginx 需要改用其他端口（建议 8082），或后续与现有入口统一。
