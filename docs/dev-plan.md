# 云端开发计划

进度：阶段 0、1、2、3 全部完成；阶段 4 **功能面已全部完成并本地实测**，只剩真机/联调落地（生产 compose 已复用 `xinqing-mysql`，HTTP 入口已改 `8082:80`，见文末「上云待办」）。阶段 3 收尾内容：设备详情历史曲线、故障统计、Nginx HTTPS、MQTT TLS、角色权限与审计完善、批量写入优化，并打通「边（ROS2）/端（Gazebo）」两条接入通道（MQTT + HTTP）。

## 阶段 0：服务器检查（已完成）

- 检查服务器是否已有 EMQX/Mosquitto：`systemctl status emqx mosquitto`。
- 检查端口占用：80、443、1883、8883、3306。
- 检查 Docker 与可用磁盘、内存。
- 结论写入 `docs/server-check.md`，再确定 Broker 容器化或复用。

## 阶段 1：基础设施（已完成）

- 编写 `deploy/docker-compose.yml`。
- MySQL 初始化 `docs/database-schema.sql`。
- Broker 启用账号与 ACL，先本机联调，TLS 上线前补齐。

## 阶段 2：最小闭环 Demo（已完成）

- Spring Boot 接入 MQTT，订阅 telemetry/heartbeat/event/cmd_ack。
- 写入 MySQL：`telemetry_data`、`device_heartbeat`（并刷新 `device.status`）、`fault_event`、`command_log`。
- 管理接口下发指令：`POST /api/devices/{id}/commands` → `robot/{deviceCode}/cmd`，回执写回 `command_log`。
- 边缘端模拟脚本 `server/mock-edge.ps1`：周期遥测 + 心跳 + 故障事件，并自动回执 `cmd_ack`。
- Vue3 设备总览页轮询设备列表，设备详情页轮询最新遥测、故障与指令记录。

## 阶段 3：页面与安全（已完成）

- `[x]` 设备详情历史曲线（ECharts 折线 + 时间窗口切换）、故障统计（等级/类型/日期）。
- `[x]` Nginx HTTPS：80 只做 301，443 起 TLSv1.2/1.3 + 安全响应头，自签证书见 `deploy/certs/`。
- `[x]` MQTT TLS：只保留 listener 8883（tlsv1.2 起），明文 1883 关闭；后端用 `MQTT_CA_CERT` 校验 broker 证书，边缘端用 `--cafile`。
- `[x]` 角色权限与审计完善：JWT 无状态鉴权（ADMIN/OPERATOR/VIEWER）+ 设备级 edge token（ROLE_EDGE），账号管理、密码修改、审计日志（登录/账号/设备/指令/凭据/边缘事件全埋点），见 `docs/rest-api.md`。
- `[x]` 前端收尾：新增「系统状态」页（`GET /api/system/stats`，5 s 自动刷新）；路由全部懒加载，首屏 JS 2.27 MB → 约 1.1 MB；接入 Tailwind v4 + shadcn-vue（新页面用、老页面保持 Element Plus，不引 preflight 避免 reset 冲突），见 `docs/local-deploy.md`「前端」。
- `[x]` 批量写入优化：遥测入队 + 单线程攒批（容量 20000、批上限 500、200ms 轮询）+ `JdbcTemplate.batchUpdate` + `rewriteBatchedStatements=true`，实测 2000 条 2000 入库、0 丢弃；坏报文只丢帧不打断 MQTT 连接（`MqttMessageRouter` 全量兜底，计数见 `/api/system/stats`）。

## 阶段 4：版本化下发 / 双向认证 / 归档 / 前端去 Element Plus（已完成）

### 参数 / 策略 / 模型版本化与下发

- `[x]` `publish` 系列接口：`/api/devices/{id}/parameters`、`/models`、`/api/strategies` 的新建/查询/`publish`，以及 `/api/devices/{id}/publishables`、`/api/edge/publishables`（见 `docs/rest-api.md`）。
- `[x]` 版本行不可变，`version` 由服务端按 `max(version)+1` 自增；状态机 `DRAFT → PUBLISHED → ACTIVE → SUPERSEDED`，**失败回执不改状态**（留在 `PUBLISHED` 可重发），重发旧版本即回滚。
- `[x]` 下发复用 `CommandService`（`cmdType` = `PARAMETER`/`STRATEGY`/`MODEL`），`command_log` 里能看到每次下发；回执走 MQTT `cmd_ack` 或 HTTP `POST /api/edge/cmd-ack`，只有回执 SUCCESS 才置 `ACTIVE`。
- `[x]` 实测：版本自增、非法名/载荷 400、不存在版本 400、下发→回执→ACTIVE、v2 生效后 v1 变 SUPERSEDED、回滚 v1、失败回执状态不变、`/api/edge/publishables` 用用户令牌 403、viewer 写 403 读 200。

### 边缘端证书双向认证

- `[x]` `mosquitto.conf`：`require_certificate true` + `use_identity_as_username true`（用户名取自证书 CN，直接命中 aclfile 的 `user <deviceCode>`）。
- `[x]` `MqttTlsSupport` 支持 PKCS12 客户端密钥库；后端新增 `MQTT_CLIENT_KEYSTORE` / `MQTT_CLIENT_KEYSTORE_PASSWORD`，两个 compose 文件都已挂载 `certs/cloud-service.p12`。
- `[x]` `server/issue-edge-cert.ps1` 签发设备证书（`deploy/certs/edge/edge-<code>.{crt,key,p12}`，CN = 设备编号）；`generate-certs.sh` 额外产出 `cloud-service.{crt,key,p12}`。
- `[x]` `server/mock-edge.ps1` 改为持证书连接（`--cert/--key`，`-u/-P` 降级为可选兜底）。
- `[x]` 实测：后端以 `cloud-service` 身份连上（TLSv1.3）；不带客户端证书 pub 直接被拒（`peer did not return a certificate`）；带 `edge-robot-001` 证书、不传 `-u` 时 broker 记录用户名 `robot-001`；`mock-edge.ps1` 上报的 2 帧遥测正常入库。

### 遥测归档与降采样

- `[x]` `GET /api/devices/{id}/telemetry/series?...&downsample=true` 等时间分桶取均值（桶内 `samples` 为原始帧数），点数上限 2000、原始扫描上限 20000 帧。
- `[x]` `TelemetryArchiveService`：把保留期之前的明细按「设备 + 小时」聚合成均值写入 `telemetry_hourly`，再按批（5000 行）删除明细；`POST /api/system/archive?retentionDays=&dryRun=`（仅 ADMIN，dryRun 默认 true），定时任务默认关闭（`TELEMETRY_ARCHIVE_ENABLED`，cron 03:30）。
- `[x]` `GET /api/devices/{id}/telemetry/hourly`、`GET /api/system/stats` 新增 `telemetry{detailRows, hourlyRows, lastArchivedAt}`。
- `[x]` 实测：dryRun 只报候选不删；真归档 4 帧 → 2 个桶、joint_1 均值 (10+20+30)/3=20 正确；保留期外明细归零。

### 前端

- `[x]` 新增「下发中心」`/publish`（4 张卡片 + 三个新建弹窗 + 下发确认 + 状态徽标，`roles: ["ADMIN","OPERATOR"]`）。
- `[x]` 设备详情历史曲线加「降采样(均值)」开关（默认开）；系统状态页加「遥测归档」卡片（明细行数/小时桶/最近归档 + 试运行/执行归档，执行归档仅 ADMIN）。
- `[x]` **Element Plus 彻底移除**：顶栏改成自建 Tailwind 导航，`ElMessage` 换成自建 `toast`（`src/lib/toast.js` + `src/components/Toaster.vue`），`package.json` 去掉 `element-plus`，`main.js` 去掉注册与 CSS；实测 7 个页面 `[class*=el-]` 节点数为 0、console 0 报错、0 失败请求。
- `[x]` 主包体积 1112 kB → **297 kB**（gzip 368 → 103 kB），`PublishCenter` 独立 chunk 约 20 kB。
- 说明：`npx shadcn-vue@latest add <component>` 需要在项目根目录执行且依赖 `components.json`；线上 registry 只发布 `new-york`/`default` 老 style，拉不到时按同样的 `data-slot` 结构手工 vendor。

## 阶段 5：对接边端（进行中）

把 `edge\edge_node`（Python 边端）接到本云端。**边端一行 REST 都不调**（纯 MQTT），所以对接面就是 topic + 载荷 + 证书三件事。

### 云端已完成（本轮）

- **两族 topic 并存**：`robot/{deviceCode}/*`（原生）与 `simulation/{simulationId}/*`（边端）同时订阅，`MqttMessageRouter` 改成按 **topic 匹配**（`EdgeMessageHandler.matches`）分发，不再靠 `endsWith` 猜。
- **适配层** `com.platform.robotcloud.simulation`：`EdgeContractAdapter` 归一化（robotId → deviceCode、`status` → `state`、三个数组 → `joints[6]`、epoch 毫秒 → 北京时间墙钟），`SimulationFaultTracker` 对 `faults[]` 做**边沿检测**（语义见 `docs/mqtt-contract.md`）。
- **设备绑定**：`device.simulation_id` 随边端上报自动回填；`device_code` 改 `utf8mb4_bin`，否则 `ROBOT-001` 会静默并到演示设备 `robot-001`。
- **下行通道**：`POST /api/devices/{id}/commands` 支持 `jointTarget` / `speed`，边端设备自动走 `simulation/{sim}/command`（`SimulationCommand` 保证字段严格对齐边端 `RobotCommand`）。
- **ACL**：`cloud-service` 读 `simulation/+/state|heartbeat`、写 `simulation/+/command`；边节点 `user SIM-001` 由 `provision-mqtt.ps1 -Simulations SIM-001` 生成。
- **迁移**：`docs/migrate-v4-simulation.sql`、`docs/migrate-v5-command-log.sql`（幂等，可重复执行）。
- **实测**：真实边端载荷经 mTLS 全链路走通——入库、6 关节归一化、毫秒时间戳换算、故障去重与「已恢复」追加、`START/STOP/MOVE_JOINT` 下发；云端下行报文用边端真实 `RobotCommand.from_dict` 反解通过。

### 边端已改（本轮一并做掉）

1. **TLS**：`_parse_broker` 支持 `ssl://`/`mqtts://`/`tls://`，建连 `tls_set(ca/cert/key)`；`edge_config.yaml` 指向 `ssl://<云端>:8883` + `edge_node/certs/`。
2. **补 `command_ack`**：边端执行后回执到 `simulation/{simId}/command_ack`，云端新增订阅与该主题的处理器，`command_log` 据此置 `SUCCESS/FAILED`。
3. **自环过滤**：边端不再把自己发的 `MOVE_JOINT_SAFE` 当云端指令解析（原先每帧报错）。
4. **ACL 补齐**：`sim_state` 读写（端→边）与 `command_ack` 写入权限。

实测（真实边端进程，非模拟）：`ssl://localhost:8884` 双向认证连上 → 上报 state/heartbeat/faults → 云端下发 `START/MOVE_JOINT/STOP` 三条指令 → 边端逐条回执 `SUCCESS`（`resultDetail` 带边端自己的说明）→ `STOP` 后云端状态变 `STOPPED`。

### 边端剩余待办

1. `[x]` **删废弃云端**（2026-09-20）：删除 `Fronted/`（另一套 Spring Boot + H2 云端）与 `test/cloud_simulator.py`（复刻它的假云端）；三方契约（openapi.yaml/schemas.json/AI_RULES.md）迁到 `Backend/edge_node/docs/contract/`，`messages.py`、`edge_cloud_integration.md` 的引用已改指新路径。
2. （可选）遗嘱消息带真实 `robotId`，让「异常掉线」落到具体设备。

## 账号治理：自助注册 + 管理员审批（已完成）

- `[x]` 数据模型：`app_user` 增加 `status`（PENDING/APPROVED/REJECTED，见 `UserStatus`），与 `enabled` 正交——status 管「是否放行入场」，enabled 管「已批准账号的临时停用」。迁移 `docs/migrate-v7-user-approval.sql`（幂等；老账号默认 APPROVED）。
- `[x]` 后端：公开 `POST /api/auth/register`（落 PENDING、不发令牌）；`login` 只放行 APPROVED+enabled，待审/驳回/停用分别给明确 401 文案；ADMIN `POST /api/users/{id}/approve|reject`；ADMIN 直接建号与系统初始化账号直接 APPROVED；「最后一个管理员」判据改为只数「已批准且启用」的 ADMIN。审计动作 `USER_REGISTER`/`USER_APPROVE`/`USER_REJECT`。
- `[x]` 前端：新增公开 `/register` 页（用户名/显示名/意向角色/两次密码），登录页加「申请注册」入口；账号管理页加状态徽标、待审批计数、待审行的「通过/驳回」按钮（通过前可临时改角色）。
- 安全说明：注册用户在审批前拿不到任何令牌；令牌无状态、不做每请求 DB 复核（沿用既有设计），已登录用户被停用后其令牌在过期前仍有效——此点未因本次改动而变化。
- 验证：前端 `npm run build` 通过（`Register`/`Users` chunk 正常）；后端因当前环境无本地 Maven、容器访问 Maven 镜像 TLS 握手被阻断而**未能在本机编译**，改动经人工审阅（审计入参元数、`UserStatus` 引用、仓库方法签名一致）。上云/联网环境按 `backend/Dockerfile` 走 `mvn package` 即可编译。

## 云端分析：健康评分 + 异常检测（已完成）

新增 `com.platform.robotcloud.analysis` 包,纯统计、跑在已有表上,**不改表、不迁移**。

- `[x]` **异常检测** `AnomalyService`:对窗口内每关节 effort/velocity 建自适应基线(均值±kσ,默认 3σ),回扫标记越界样本。上限:扫 20000 帧、返回 500 个异常点、<30 帧标 insufficient、std<1e-6 的关节不判异常(防抖动误报)。产出每关节基线 + 异常点明细 + 异常帧占比。选「设备自身近期基线」而非固定阈值,捕捉「相对自己的突变」,好解释。
- `[x]` **健康评分** `HealthService`:综合分 = 可用性×0.25 + 故障×0.35 + 遥测×0.40,每项 0~100、越高越好,分级 A≥90/B≥75/C≥60/D<60。可用性看设备状态 + 最近心跳/遥测新鲜度(2min 满分、30min 归零、线性过渡,OFFLINE 再对折);故障按窗口内 WARNING/ERROR/CRITICAL 加权扣分(4/12/25,封顶 100);遥测 = 100×(1−异常帧占比)。可解释优先,低分能直接看出扣在哪。
- `[x]` **接口** `AnalysisController`(全 GET、只读、任意登录角色可看,落 SecurityConfig 的 anyRequest):`GET /api/analysis/health`(机队总览,按分升序)、`/api/analysis/devices/{id}/health`(单设备)、`/api/analysis/devices/{id}/anomalies`(异常明细)。见 `docs/rest-api.md`。
- `[x]` **前端**:新增「分析中心」`/analysis`(4 张汇总卡 + 机队健康表,点行进设备详情;顶栏导航在设备总览后);设备详情页加「健康评分」卡(综合分 + 三分项 SubScore 条 + 异常关节徽标 + 窗口故障计数 + notes);新增复用组件 `SubScore.vue`;`api/analysis.js`。前端 `npm run build` 通过(`Analysis` chunk 约 7 kB)。
- 验证同账号治理:前端 build 过;后端因本机无 Maven、容器访问 Maven 镜像 TLS 握手被阻断**未能本机编译**,改动经人工审阅(仓库方法签名、lambda 捕获、嵌套类私有字段访问、记录构造)。上云/联网环境按 `backend/Dockerfile` 走 `mvn package`。

## 云端分析（第二批）：趋势/预测性维护 + 下发效果分析（已完成）

延续第一批风格（`analysis` 包、纯统计、只读 GET、不改表）。2026-09-20 本机联网编译 + 容器重启 + 冒烟全通过。

- `[x]` **趋势 / 预测性维护** `TrendService`：每关节 **effort** 等时间分桶取均值 → 最小二乘回归求斜率 → 用异常检测基线上界（mean+3σ）外推「照此趋势多久到危险线」。`GET /api/analysis/devices/{id}/trend`。斜率≤0 或已越界不外推预警。只做 effort（最反映负载/磨损）。危险线复用异常检测基线，不另立阈值。
- `[x]` **下发效果分析** `PublishEffectService`：以指令回执时刻为界，对比前后各 30 分钟（可调）各关节 effort 均值/波动，给 `verdict`（有效/无明显变化/样本不足）。`GET /api/analysis/commands/{commandId}/effect`。把「下发—回执」与「遥测」接成闭环。
- `[x]` **复用**：新增包内 `JointMetrics` 工具类（joints 载荷解析 + Accumulator），不动第一批已上线的 `AnomalyService`；两个新服务和 TrendService 的基线都复用 `AnomalyService.detect(...)`。
- `[x]` **前端**：设备详情页并入「趋势预测（力矩）」卡（每关节斜率/当前值/预计到上界/结论，预警行高亮）与指令记录行的「看效果」弹窗（before/after 逐关节对比 + verdict）。`api/analysis.js` 加 `getDeviceTrend`/`getCommandEffect`。前端 `npm run build` 通过。
- 本批**无 DB 改动、无 migration**。

## 端到端验收冒烟（已完成）

- `[x]` `server/smoke-e2e.sh`：bash + curl，打本地运行栈，串「健康检查 → 自助注册(PENDING) → 管理员登录 → 审批 → 新账号登录 → 取设备 → 下发(按设备类型选 cmdType) → 分析五连(health/设备health/anomalies/trend/effect) → 清理测试账号」，逐步打印 PASS/FAIL。2026-09-20 实测 **14 PASS / 0 FAIL**。
- 坑：请求体必须纯 ASCII——Git Bash（GBK locale）会把中文经 `curl -d` 传成坏字节，后端报 `Invalid UTF-8 middle byte`；边端设备（绑 simulationId）下发只认 `START/STOP/MOVE_HOME/MOVE_JOINT`，脚本据 `simulationId` 自动选 cmdType。

## 上云待办（真机部署）

- 生产 compose 已复用宿主机已有的 `xinqing-mysql`（`backend` 通过外部 `xinqing_default` 网络直连）。
- Nginx 已改映射到 `8082:80`（宿主机 80 被占），HTTPS 正式入口仍是 `443:443`；没域名没证书，`8082` 默认直接提供页面与 `/api` 反代，**`NGINX_HTTP_REDIRECT` 必须保持 `0`**（设为 `1` 就会 301 到自签的 443）。
- 2026-09-21 线上实测（`106.15.43.100`）：`8082` 实际返回 `301 → https://<ip>:443/`，443 挂的是自签证书，微信/QQ 内置浏览器不接受自签证书也不弹「继续访问」，于是「电脑能开、手机打不开」。这就是手机端打不开的直接原因；排查步骤与三条出路（http 直供 / 域名 + acme.sh DNS-01 可信证书 / Cloudflare Tunnel）见 `deploy/README.md` 的「手机 / 微信打不开页面」。
- 内存上限合计 1152M（mqtt 256M + backend 768M + nginx 128M；MySQL 复用宿主机 `xinqing-mysql`，不再占本项目额度），对齐服务器「3.4G 总量、可用约 1.9G、无 Swap」；不紧张但仍要逐个起服务观察。
- 部署顺序：生成/分发证书（`generate-certs.sh` + `issue-edge-cert.ps1`）→ 构建后端镜像与前端 `dist` → `provision-mqtt.ps1` 落 broker 账号与 ACL → `docker compose up -d` → 按 `deploy/README.md` 的「双向认证自检」验一遍。
