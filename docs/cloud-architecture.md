# 云端总体架构设计

## 服务划分

| 服务 | 容器 | 职责 | 建议资源 |
|---|---|---|---|
| Nginx | nginx | 托管 Vue3 构建产物，反向代理 `/api` | 128 MB |
| Spring Boot | backend | REST API、MQTT 收发、业务处理 | 768 MB–1 GB |
| MySQL | mysql | 设备、遥测、故障、版本、审计数据 | 512 MB–1 GB |
| MQTT Broker | mosquitto（默认） | 边缘与云端消息通道 | 128–256 MB |

说明：Broker 最终选型以服务器实际检查结果为准。若服务器已有 EMQX 且运行稳定，可复用；否则 2核4G 环境优先选择 Mosquitto。

## 数据流

上行：Gazebo → ROS2 → 边缘控制程序 → MQTT → Cloud Broker → Spring Boot → MySQL → Vue3

下行：Vue3 → REST API → Spring Boot → 校验/落库 → MQTT 下发 → 边缘端执行 → 回执 → `command_log`

## 职责边界

- 边缘端：实时控制、故障检测、容错逻辑。
- 云端：设备管理、数据存储、历史查询、分析、参数/策略/模型版本管理与下发。
- 云端不参与机械臂毫秒级实时控制。
- Gazebo/ROS2 不部署到云服务器。

