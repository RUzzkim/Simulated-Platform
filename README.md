# 仿真机械臂云端平台

> **V2.0 研发方向已确认，方案文档**：[智控臂联 V2.0 研发方案](docs/v2.0-development-proposal.md)。V2.0 聚焦单关节卡滞后的任务可恢复性，继续采用端—边—云结构，以 Python 仿真和边缘算法验证，MATLAB 与真实机械臂不作为开发前提。新增功能和实验仍属方案，下文描述仓库现有的 V1 资产。

## 协作前先看

1. 阅读 `docs/v2.0-development-proposal.md`，团队共同冻结实验阈值、场景、随机种子与接口字段。
2. 按本机环境验证 Docker、ROS 2 仿真端和 Python 边缘节点。Gazebo 物理场景不是首阶段算法验证前提，现有 Python plant 可用于确定性实验。
3. 实验使用唯一 `run_id`，保存算法版本、场景参数、随机种子、故障与决策时刻及原始时间序列。
4. 根目录 `.gitignore` 已排除本地环境文件、部署证书/私钥和构建产物。仅提交 `.env.example`，不要提交真实凭据。
5. 方案计划截止日期为 **2026 年 12 月 9 日**。成果数字须可追溯到仿真记录并注明仿真条件。

---

这是「端—边—云」协同的工业机械臂智能控制与仿真平台。仓库现已收拢三层全部代码：**端**（`sim/` 仿真端 + 液压臂孪生）、**边**（`edge/` ROS 2 实时控制与容错）、**云**（`backend/`+`frontend/`+`deploy/` 设备管理、数据存取、故障统计与指令下发）。云端不碰毫秒级实时控制，那部分在边端。

## 三层各管什么

| 层 | 在哪 | 干什么 |
|---|---|---|
| 端 | `sim/`（ROS 2 仿真端 + 液压臂数值孪生） | 实时仿真 6R 机械臂，产生关节状态、接收关节指令；含 Gazebo 物理世界、作业场景与故障注入 |
| 边 | `edge/edge_node`（仓库里的 Python / ROS 2 边端） | 100Hz 实时处理：信号清洗、故障检测、容错控制 |
| 云 | 就是这个仓库 | 设备管理、数据存储、历史查询、故障统计、指令与配置下发、账号与审计 |

凡是「每秒要跑一百次」的事都留在边端。云端只负责把数据存好、给人看、按需往下发。

## 现在能做什么

- 登记设备和仿真实例，云端按设备签发独立的 MQTT 客户端证书和 edge token。凭据在库里用 AES-256-GCM 加密存放，设备详情页的「边缘接入」可以直接看（ADMIN / OPERATOR）。
- MQTT 上行遥测按批入库，设备详情页能看到关节位置、速度、力矩的历史曲线。心跳单独一条链路，用来判断设备在线状态。
- 边端上报的 `faults[]` 表示「当前这一帧有哪些故障在活动」，不是事件流。云端自己做边沿检测：故障出现时插一条记录，恢复时把那条追加上「（已恢复，持续 Ns）」，不会每帧都刷一条。
- `POST /api/devices/{id}/commands` 下发指令，支持 `jointTarget`、`speed`、停机、回零。下发走 simulation 契约，边端执行后回执，`command_log` 从 `PENDING` 变成 `SUCCESS` 或 `FAILED`。
- 发布中心对参数、策略、模型三类配置做版本管理，带 `DRAFT` / `PUBLISHED` / `ACTIVE` / `SUPERSEDED` 状态和归档。
- 账号分 ADMIN / OPERATOR / VIEWER 三种角色，JWT 认证；谁在什么时候做了什么，全量落审计表。
- 系统状态页展示 MQTT 连接情况、遥测写入丢弃数、坏报文计数等运行时指标，出问题先看这一页。

## 技术栈

- 后端：Spring Boot 3.4.5、Java 21、Spring Data JPA、Maven，产物 `robot-cloud-backend`。
- 消息：Eclipse Mosquitto 2，TLS 8883 双向认证（`require_certificate true` + `use_identity_as_username true`，身份取自客户端证书 CN），明文 1883 关闭。
- 数据库：MySQL 8。`device_code` 用 `utf8mb4_bin`，否则 `ROBOT-001` 会和演示设备 `robot-001` 撞成同一个。
- 前端：Vue 3.5 + Vite 6 + Vue Router + axios + ECharts 6 + Tailwind CSS 4 + shadcn-vue（底层 reka-ui）。
- 部署：Docker Compose + Nginx，80 只做 301 跳转，443 起 TLSv1.2/1.3 并反代 `/api`。

## 本地跑起来

在 `deploy` 目录里执行：

```powershell
copy .env.example .env          # 填 MySQL / MQTT 密码
.\certs\generate-dev-certs.ps1  # 自签 CA + 服务端证书
docker compose -f docker-compose.local.yml up -d --build
```

起来之后：

- 页面：`https://127.0.0.1:8443`。自签证书，浏览器提示不安全，点继续访问就行。
- MQTT：`ssl://127.0.0.1:8884`（容器内 8883）。
- 后端直连：`http://127.0.0.1:8090/api`，仅供本机调试。

本地演示账号：`admin` / `admin-local-pass`、`operator` / `operator123456`、`viewer` / `viewer123456`。只有 `ADMIN_SEED_DEMO_USERS=true` 时才创建，生产默认关闭。

想冒烟：`server\publish-mqtt.ps1 -DeviceId robot-001 -Count 5` 只发点遥测；想跑通「遥测 → 指令 → 回执」整条闭环，用 `server\mock-edge.ps1 -DeviceId robot-001 -Iterations 60 -EmitFault`。

只改代码、单独构建：

```powershell
docker build -t robot-backend:local backend
cd frontend; npm run build
```

## 目录结构

云端、边端和仿真端合并成一个仓库，按层分目录。云在 `backend/`、`frontend/`、`deploy/`、`server/`，边在 `edge/`，端在 `sim/`，各层共用的契约文档在 `docs/` 和 `edge/edge_node/docs/`。

```
platform/
├── backend/                    云：Spring Boot 后端（Java 21 + Maven）
│   ├── src/main/java/com/platform/robotcloud/
│   │   ├── device/ telemetry/ heartbeat/ event/   ← 设备、遥测、心跳、故障事件
│   │   ├── command/ publish/ credential/          ← 指令、版本化下发、设备凭据
│   │   ├── mqtt/ simulation/                      ← MQTT 路由 + 边端 simulation 契约适配
│   │   └── security/ audit/ system/ support/      ← 认证鉴权、审计、系统指标、通用支撑
│   ├── pom.xml                  依赖与构建
│   └── Dockerfile               后端镜像
│
├── frontend/                   云：Vue 3 前端（九个页面：Login / Register / DeviceList / DeviceDetail /
│   │                           Analysis / PublishCenter / Users / AuditLogs / SystemStatus）
│   ├── src/api                 后端接口封装
│   ├── src/views               页面组件
│   └── dist                    构建产物（nginx 直接挂载）
│
├── edge/                       边：ROS 2 / Python 实时节点
│   ├── edge_node/              边端主项目（ROS 2 包）
│   │   ├── edge_node/          源码包
│   │   │   ├── main.py         入口：五级流水线（滤波 → 状态推断 → 故障检测 → 容错 → 上报）
│   │   │   ├── config/         配置加载（YAML + 环境变量覆盖）
│   │   │   ├── control/        自适应神经网络控制器（RBF）
│   │   │   ├── fault/          故障检测与容错
│   │   │   ├── mqtt/           MQTT 客户端（paho-mqtt，支持 TLS 双向认证）
│   │   │   ├── processor/      信号滤波、状态推断
│   │   │   ├── ros2/           ROS 2 话题收发
│   │   │   └── utils/          日志
│   │   ├── config/edge_config.yaml   边端配置（身份、MQTT、算法参数）
│   │   ├── launch/             ROS 2 launch 文件
│   │   ├── test/               单元测试 + 仿真联调脚本
│   │   ├── docs/               edge_cloud_integration.md（联调文档）、contract/（openapi 契约）
│   │   ├── Dockerfile          边端镜像（ros:humble + colcon 构建）
│   │   ├── docker-compose.yml  边端部署编排
│   │   └── deploy.sh           一键部署（up / stop / logs / status）
│   └── INTERFACE_ALIGNMENT.md  边端与云端接口对齐说明
│
├── sim/                        端：仿真端（ROS 2 实时仿真 + 液压臂数值孪生）
│   ├── gazebo_arm/             ROS 2「端」包（ament_python）
│   │   ├── gazebo_arm/         源码：plant（物理 plant + 故障注入）、plant_node、
│   │   │                       scenarios（搬运/喷号/分拣作业）、gazebo_bridge（Gazebo↔边端）、
│   │   │                       grasp_node（抓取）、gen_urdf（工业臂 URDF 生成）
│   │   ├── urdf/               hydraulic_arm.urdf + gazebo_arm.gazebo.xacro（ros2_control）
│   │   ├── worlds/             steel_yard.world（钢材车间物理世界）
│   │   ├── launch/             sim_arm.launch.py（RViz 路径）、gazebo.launch.py（Gazebo 路径）
│   │   ├── config/ rviz/ docs/ 控制器配置、RViz、WSL2 快速上手
│   │   └── docker-compose.yml  端+边一键联调（ros:humble）
│   └── hydraulic-arm/          液压臂数值孪生（控制器整定与阈值校核，仅仿真结论）
│       ├── python_twin/        Python 孪生（可跑，产物在 results/）
│       ├── shared/             RBF 中心表
│       ├── docs/               建模推导与参数依据
│       └── results/            报告 + 跟踪/误差/力矩/压力/收敛 5 图 + 磨损数据集
│
├── deploy/                     云：生产部署（Docker Compose + Nginx + Mosquitto + 证书）
│   ├── docker-compose.yml      生产编排（mqtt + backend + nginx）
│   ├── docker-compose.local.yml 本地编排（多一个 mysql）
│   ├── mosquitto/              mosquitto.conf、ACL、密码文件
│   ├── nginx/                  nginx 模板（80 跳 301，443 反代 /api）
│   ├── certs/                  CA、服务端证书、设备证书
│   └── README.md               生产部署说明
│
├── server/                     云：运维脚本
│   ├── provision-mqtt.ps1      按云端凭据生成 passwordfile + ACL 并热加载
│   ├── issue-edge-cert.ps1     给设备/边端签发客户端证书
│   ├── mock-edge.ps1           mock 边端（跑通遥测 → 指令 → 回执）
│   ├── publish-mqtt.ps1        发点遥测冒烟
│   └── setup-cloud.sh          服务器初始化（建库、导入 schema、起 broker；deploy/.env 只补键不覆盖，起完做一遍 mTLS/ACL 自检）
│
└── docs/                       云：文档（接口契约、数据库、迁移脚本）
```

边端不调 REST，和云端只走 MQTT，对接面是 `docs/mqtt-contract.md` 里的 topic 和载荷。两端接口对齐看 `edge/INTERFACE_ALIGNMENT.md`。

## 文档在哪

- `deploy/README.md`：生产部署，证书怎么签、broker 怎么配、上线后怎么自检。
- `docs/local-deploy.md`：本地这套怎么起、账号从哪来、怎么对接边和端。
- `docs/mqtt-contract.md`：MQTT topic 与 JSON 载荷契约，改协议先看它。
- `docs/security/encryption-verification.md`：加密模块验证报告（AES-256-GCM + TLS 的吞吐损耗与对抗测试实测），附可复现基准脚本。
- `docs/rest-api.md`：REST 接口清单。
- `docs/database-schema.sql`：建表语句，同目录 `migrate-v*.sql` 是增量迁移。
- `docs/cloud-architecture.md`、`docs/dev-plan.md`：架构设计与开发计划，想了解为什么这么分层可以翻。
- `edge/edge_node/docs/edge_cloud_integration.md`：边端那份联调文档。
- `sim/gazebo_arm/README.md`：仿真端（ROS 2 / Gazebo）怎么起、怎么接边端、作业场景与故障注入、验证状态。
- `sim/hydraulic-arm/README.md`：液压臂数值孪生的建模、参数、控制器整定与边端阈值校核（仅仿真结论）。
- `edge/edge_node/test/reports/comparison_report.md`：传统控制 vs 自适应 NN、容错 ON/OFF 的 48 组对比测试报告（含性能对比图与收敛曲线）。
- `docs/V1-evidence-index.md`：V1.0 全部佐证材料的一页索引（对到计划书指标与附录清单）。

## 几个会踩的坑

- 证书 CN 就是身份。设备证书的 CN = 设备编号，边端节点证书的 CN = simulationId（如 `SIM-001`）。CN 不对，broker 的 ACL 就命不中，表现是「能连上但收不到消息」，很难查。
- 改完 `mosquitto.conf` / `aclfile` / `passwordfile` 一定要让 broker 重新加载。`server\provision-mqtt.ps1` 里已经带了 `SIGHUP`；改 `mosquitto.conf` 本体要 `up -d --force-recreate mqtt`，只改宿主机上的文件不会生效。
- `JWT_SECRET` 和 `CREDENTIAL_KEY` 一改，所有旧令牌和已签发凭据立刻失效，要重新签发并重跑 `provision-mqtt.ps1`。生产环境这两个必须是随机值。
- 自签证书的 SAN 要覆盖边端实际连接的域名或 IP。一旦重签，边端也要同步换 `ca.crt` 和设备证书。
