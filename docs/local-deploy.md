# 本地部署说明

1. 在 `deploy` 目录复制 `.env.example` 为 `.env`，填写 MySQL 与 MQTT 密码。
2. 生成 Mosquitto 密码文件：
   ```powershell
   docker run --rm -v ${PWD}/mosquitto:/mosquitto/config eclipse-mosquitto:2 mosquitto_passwd -c /mosquitto/config/passwordfile cloud-service
   ```
3. 生成本地开发证书（自签 CA + 服务器证书，SAN 覆盖 `localhost/mqtt/nginx/robot-backend/127.0.0.1/::1`）：
   ```powershell
   .\certs\generate-dev-certs.ps1
   ```
   产物：`certs/ca.crt`、`certs/ca.key`、`certs/server.crt`、`certs/server.key`（默认 825 天）。`*.key` 与 `ca.key` 是私钥，不要外发或提交。
4. 构建并启动本地环境：
   ```powershell
   docker compose -f docker-compose.local.yml up -d --build
   ```
5. 访问入口（页面与 MQTT 都已走 TLS）：
   - 页面：`https://127.0.0.1:8443`（自签证书）；`http://127.0.0.1:8091` 默认直接提供页面，`NGINX_HTTP_REDIRECT=1` 时才改成 301 跳 HTTPS。
   - 后端 API：`https://127.0.0.1:8443/api`（直连后端 `http://127.0.0.1:8090/api` 仍然可用，仅供本机调试）。
   - MQTT：`ssl://127.0.0.1:8884`（容器内 8883），账号见 `.env`；明文 1883 已关闭。
   - 用的是自签证书：浏览器会提示「不安全」，本地点「继续访问」即可；命令行用 `curl -k`，MQTT 客户端用 `--cafile ca.crt`。
   - **时区**：backend 与 mysql 容器都设了 `TZ=Asia/Shanghai`，库里所有 DATETIME 存的是北京时间墙钟，
     界面原样展示。所以 `docker exec robot-mysql-local mysql ... -e "select now()"` 出来的就是本地时间，
     不用再自己加 8 小时。旧库（2026-09-19 之前）是 UTC 墙钟，执行 `docs/migrate-v6-local-time.sql` 一次性平移。
6. 发布测试遥测（只发遥测，用于快速冒烟）：
   ```powershell
   ..\server\publish-mqtt.ps1 -DeviceId robot-001 -Count 5
   ```
   默认就是 TLS：`-Port 8883 -CaFile /mosquitto/config/certs/ca.crt`（`-CaFile` 是容器内路径，脚本通过 `docker exec` 在 broker 容器里发消息）。
7. 跑通完整闭环（遥测 + 心跳 + 故障事件，并自动回复 `cmd_ack`）：
   ```powershell
   $env:MQTT_SERVICE_USERNAME = "cloud-service"
   $env:MQTT_SERVICE_PASSWORD = "local-dev-pass"
   ..\server\mock-edge.ps1 -DeviceId robot-001 -Iterations 60 -EmitFault
   ```
8. 验证闭环：
   - 打开 `https://127.0.0.1:8443`，设备总览每 5 秒刷新，出现 `robot-001`。
   - 进入设备详情，最新遥测每 2 秒刷新，能看到关节数据与心跳带来的在线状态。
   - 在详情页下发指令，`mock-edge.ps1` 仍在运行时会在几秒内回执，指令记录由 `PENDING` 变为 `SUCCESS`。

## 角色与账号

开关都在 `deploy/.env`：首次启动（`app_user` 表为空）时用 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 建管理员，`ADMIN_SEED_DEMO_USERS=true` 时额外建两个演示账号（生产为 `false`）。

| 账号 | 密码（本地） | 角色 | 能干什么 |
|---|---|---|---|
| `admin` | `admin-local-pass` | ADMIN | 全部，含账号管理与审计 |
| `operator` | `operator123456` | OPERATOR | 设备/指令/凭据/审计查询，不能管账号 |
| `viewer` | `viewer123456` | VIEWER | 只读 |

- 页面必须登录后才能进（路由守卫），令牌存在浏览器本地，`401` 会自动跳登录页；顶栏可改密码与退出。
- 账号管理页只在 ADMIN 下显示；「不能停用/降级自己」「不能移除最后一个管理员」由后端强制校验，不只是前端隐藏。
- `JWT_SECRET`（≥32 字节）与 `CREDENTIAL_KEY`（设备密码/令牌加密用）在 `.env` 里，**生产必须换成随机值**，改了以后所有旧令牌和已签发凭据都会失效。

## 对接边和端

「边」是 ROS2 边缘节点，「端」是 Gazebo 仿真端，两条通道落库逻辑完全一致：

1. **MQTT 通道（推荐，边）**：设备用云端签发的独立账号连 `ssl://<host>:8883`（本地 `127.0.0.1:8884`），按 `docs/mqtt-contract.md` 上报四个 topic，订阅 `robot/<code>/cmd` 并回 `cmd_ack`。
2. **HTTP 通道（端/无 MQTT 环境）**：用 edge token 调用 `/api/edge/*` 上报，指令改成主动拉取 + 回执。

落地步骤：

```powershell
# 1) 页面「设备详情 → 边缘接入」签发凭据，或直接调 API
#    POST /api/devices/1/credentials  → 拿到 mqttUsername/mqttPassword/edgeToken
# 2) 把设备账号写进 broker 的 passwordfile/aclfile（每台设备独立账号 + 严格 ACL）
$env:ADMIN_PASSWORD = "admin-local-pass"
..\server\provision-mqtt.ps1
# 3) 边缘端（MQTT）：遥测 + 心跳 + 故障，并自动回执 cmd
$env:MQTT_DEVICE_USERNAME = "robot-001"
$env:MQTT_DEVICE_PASSWORD = "<详情页里的 mqttPassword>"
..\server\mock-edge.ps1 -DeviceId robot-001 -Iterations 60 -EmitFault
# 4) 仿真端（HTTP）：同一条链路的 HTTP 版本
..\server\mock-edge-http.ps1 -DeviceId robot-001 -Iterations 10 -EmitFault -AckCommands
```

- `provision-mqtt.ps1` 会热加载 broker 配置（`docker cp` + `SIGHUP`），不用重启容器；重新签发/轮换凭据后再跑一次即可。
- 凭据只在设备详情页「边缘接入」可见（ADMIN/OPERATOR），库里用 AES-256-GCM 加密存放；轮换后旧 edge token 立即失效，旧 MQTT 密码在下次 `provision-mqtt.ps1` 后失效。
- 页面「边缘接入」卡片里的 broker 地址/端口/topic 列表就是给边缘端直接抄的，避免手写错。

## 批量写入与吞吐

高频遥测不逐条落库：MQTT 线程只把帧入队，单线程攒批后走 JDBC `batchUpdate`（容量 20000、单批上限 500、200ms 轮询、`rewriteBatchedStatements=true`）。

- 观测：`GET /api/system/stats` → `telemetryWriter`（`enqueued`/`inserted`/`dropped`/`failedFlushes`/`lastBatchSize`）与 `mqttRouter`（`malformedDropped`/`handlerFailed`）。
- 实测（本地容器）：2000 条突发遥测 → `enqueued=2000, inserted=2000, dropped=0, failedFlushes=0`，DB 行数一致；broker 侧旁路订阅者也收到 2000 条，即「broker 收到的，云端一条不丢」。
- 队列满时**丢弃并计数**（遥测允许丢帧，但不允许阻塞上报线程）；`dropped` 持续增长说明需要调大队列或加消费者。
- 压测注意：`mosquitto_pub -l -q 1` 单连接灌 2000 条会**在 700–1900 条之间自己断链并静默结束**（客户端工具限制）。分块发（每块 100 条、独立连接）就能 2000/2000；QoS 0 单连接也能灌完 2000 条。别用 `--repeat N --repeat-delay 2` 这类命令做压测（delay 单位是秒，2000 条要跑一小时，还会把脏载荷持续灌进 broker）。

## 前端（Tailwind + shadcn-vue）

页面：设备总览 / 设备详情（历史曲线+故障统计）/ 系统状态 / 下发中心 / 审计日志 / 账号管理 / 登录。**Element Plus 已完全移除**，`package.json` 里不再有 `element-plus`，`main.js` 也不再注册它。

- **系统状态页 `/system`**：读 `GET /api/system/stats`，展示遥测批量写入水位（enqueued/inserted/dropped/failedFlushes/最近批大小与耗时）、MQTT 坏报文计数、设备在线数与运行时长；5 秒自动刷新，可暂停。所有登录角色可见。
- **路由懒加载**：`src/router/index.js` 全部改成 `() => import(...)`。全部页面切完后首屏主包 **297 kB（gzip 103 kB）**（Element Plus 时期是 1112 kB / gzip 368 kB）；ECharts 随设备详情页单独成 chunk（约 1.1 MB，只在进详情页时加载），下发中心 `PublishCenter` 也是独立 chunk（约 20 kB）。
- **Tailwind v4 + shadcn-vue**（全站统一）：
  - 依赖：`tailwindcss` + `@tailwindcss/vite` + `reka-ui` + `class-variance-authority` + `clsx` + `tailwind-merge` + `lucide-vue-next`；别名 `@` → `src`（`vite.config.js` + `jsconfig.json`）；`components.json` 已就位。
  - 全局样式只有 `src/assets/tailwind.css` 一个入口，**刻意只引 `tailwindcss/theme.css` + `tailwindcss/utilities.css`，不引 preflight**（坑：preflight 的 `h1~h6 { font-size: inherit; font-weight: inherit }` 会把登录页大字标题压成正文大小；Element Plus 的样式是无层级的，靠层叠顺序兜不住）。
  - shadcn 组件自己在 `@layer base` 里做了 UA 兜底（border/背景/字体继承、table 的 border-spacing 等），并且**只按 `[data-slot]` 命中**——所有 shadcn-vue 组件都带这个属性，Element Plus 不带，所以互不影响。
  - 组件放在 `src/components/ui/*`（button / badge / card / separator / table / dialog / input / label / select / switch / textarea / dropdown-menu），`cn()` 在 `src/lib/utils.js`。
  - 不引 preflight 的副作用要自己兜：`input/textarea/button` 的 UA 字体会和正文不一致（已在 `@layer base` 里对 `[data-slot="input"|"textarea"|"select-trigger"|"button"|"badge"|"dialog-close"]` 统一 `font: inherit`，并清掉 `button` 的 UA 背景/边框）；`dialog-close` 这类裸 `<button>` 还要给 `appearance-none border-0 bg-transparent`。`dl/dt/dd` 的 UA 缩进（`dd { margin-inline-start: 40px }`）不在 `[data-slot]` 范围内，**页面里用 `div` 排版或自己清 margin**，别指望 base 层。
  - 再加组件：`npx shadcn-vue@latest add <component>`。当前机器访问不了 `shadcn-vue.com`（registry 超时），实测 CLI 能正常读到本项目的 `components.json`，只是拉不到 registry；能上外网时直接可用，否则按同样的 `data-slot` 结构手工 vendor 即可。
- **下发中心 `/publish`（阶段 4 新增）**：4 张卡片——当前生效（参数/策略/模型各显示 `ACTIVE` 版本）、参数版本、模型版本、策略版本；三个新建版本弹窗 + 下发确认弹窗；状态徽标区分 `DRAFT`/`PUBLISHED`/`ACTIVE`/`SUPERSEDED`，操作列由 `canWrite()` 控制（VIEWER 只读）。路由带 `roles: ["ADMIN","OPERATOR"]`。
- **已统一到 shadcn-vue 的页面（7 个页面全部）**：设备总览 `/`（表格 + 注册弹窗）、设备详情 `/devices/{id}`（概览、最新遥测、位置历史曲线、故障统计、边缘接入、指令下发、故障事件、重命名弹窗）、审计日志 `/audit-logs`（筛选卡片 + 表格 + 分页条）、账号管理 `/users`（表格 + `Select` 改角色 + `Switch` 启用/停用 + 新建账号 / 重置密码 / 角色变更确认三个 Dialog）、登录 `/login`（Card + 表单）。
  - 顶栏账号区（角色徽标 `Badge`、`DropdownMenu` 账号菜单、修改密码 `Dialog`、退出登录确认 `Dialog`）也已切到 shadcn，`ElMessageBox.confirm` 全部换成自建 Dialog；`el-dropdown`/`el-dialog`/`el-tag`/`el-form`/`el-input`/`el-button` 在 `src/` 里已无引用。
  - **Element Plus 已彻底移除**：顶栏改成自建 Tailwind 导航（`App.vue` 里的 `header nav a`，当前路由高亮 `border-[#409eff]`），`ElMessage` 由自建轻提示替代（`src/lib/toast.js` + `src/components/Toaster.vue`，挂在 `App.vue`，3.5 s 自动消失），全部约 50 处 `ElMessage.*` 已换成 `toast.*`。实测 7 个页面 `[class*=el-]` 节点数为 **0**，console 0 报错、0 失败请求。
  - 只重写模板与样式：接口调用、轮询周期（2 s / 5 s / 10 s / 30 s）、分页步长与 `canWrite()` 权限判断、ECharts 配置、筛选参数拼装与全部中文文案都保持原样。
  - 两处刻意的替换：① 审计页原来的 `el-date-picker[datetimerange]` 换成两个 **原生 `datetime-local` 输入**（不引日期组件，提交前用 `toLocalIso` 转成**本地墙钟**，与库里口径一致）；② 筛选下拉的「全部」用哨兵值 `__all__`，因为 reka-ui 的 `Select` 不接受空字符串作为选项值，提交前再映射回空串。
- **约定**：页面统一用 Tailwind utilities + `src/components/ui`；**不要引 preflight**（原因见上）；需要新组件时优先 `npx shadcn-vue@latest add <component>`（该命令要在项目根目录跑、且依赖已就位的 `components.json`），拉不到 registry 时按同样的 `data-slot` 结构手工 vendor 到 `src/components/ui/`。

### 截图回归（改全局样式后必跑）

前后端起来后：

```powershell
cd frontend
npm run shots          # 输出到 frontend/.shots/，可用 EDGE_PATH 指定浏览器
```

用本机 Edge（headless + CDP）+ 会话令牌访问 6 个页面截图，不依赖 Puppeteer。改完 `tailwind.css`、`vite.config.js` 或全局样式后跑一次，和改动前的图对比：本次引 Tailwind 时就是靠它发现「登录页标题被 preflight 压小」，修完 login 页面像素级差异回到 0.00%。

重写设备列表/详情后又跑了一轮（用 headless 浏览器 + canvas 逐像素比对）：`login` 0.00%、`users` 0.03%、`system` 0.11%、`audit-logs` 2.87%（后三者的差异来自实时数据和新增审计行使表格位移），也就是没动过的 Element Plus 页面零回归；`devices` / `device-detail` 的差异就是这次重写本身。Dialog / Select 的交互态（弹窗标题与描述、下拉展开与选中项）也用同一套 CDP 脚本点开截图确认过。

顶栏账号区（`Badge` + `DropdownMenu` + 修改密码 / 退出登录两个 Dialog）切完后同样用 CDP 真实鼠标事件跑过一遍：下拉展开、菜单项与标题、修改密码的短口令拦截 / 原密码错 / 成功改密 / 口令还原（改完新口令 200、旧口令 401）、退出登录取消后仍在 `/` 且令牌还在、确认后落到 `/login` 且令牌清空，console 0 报错。

账号管理 / 登录切完后再跑一轮：6 个页面逐个巡检 console 与网络，0 报错、0 失败请求（`login` 11 个 `data-slot`、`users` 54 个、`device-detail` 253 个）。交互态用同一套 CDP **真实鼠标事件**脚本点开验证：弹窗标题与描述跟随所点行（`为 viewer 设置新密码（至少 8 位）。`）、自己那行的 `Select`/`Switch` 带 `disabled`、角色确认弹窗取消后库与界面都回滚成 `OPERATOR`；重置密码走完整闭环——提交后弹窗关闭、新口令登录 200/`VIEWER`、旧口令 401，最后把口令还原并通过接口复核。注意测试脚本里**别用 `row.querySelector('button')` 取行内按钮**：一行的第一个 `<button>` 是 `Select` 触发器的，会静默点错元素（`Switch` 也是 `<button>`），要按文案 `find(b => b.textContent.includes('重置密码'))` 定位。
## 证书与 TLS

- 生成/续期：`deploy\certs\generate-dev-certs.ps1 [-Days 825]`（内部用 `alpine/openssl` 容器跑 `generate-certs.sh`，所以本机不需要装 openssl）。SAN 列表在 `certs/openssl-san.cnf`，换了域名或 IP 要改这里再重新生成。
- Nginx：80 只做 301，443 起 `TLSv1.2 TLSv1.3` + `X-Content-Type-Options/X-Frame-Options/Referrer-Policy`，配置模板 `nginx/default.conf.template`，HTTPS 端口由 compose 注入（本地 `8443`，生产 `443`）。
- Mosquitto：只保留 `listener 8883`（`tls_version tlsv1.2`），**已启用双向认证**：`require_certificate true` + `use_identity_as_username true`（用户名直接取证书 CN，命中 `aclfile` 里的 `user <deviceCode>`）。证书与账号文件由 compose 的启动命令从 `/mosquitto/config` 拷到 `/mosquitto/{certs,conf}` 再 `chown mosquitto`：mosquitto 启动时会丢掉补充组，直接读绑定挂载上 0600/0640 的私钥会失败。
- 后端：`MQTT_BROKER=ssl://mqtt:8883` + `MQTT_CA_CERT=/certs/ca.crt`（PEM 自签 CA，校验 broker 证书），**再挂自己的客户端证书**：`MQTT_CLIENT_KEYSTORE=/certs/cloud-service.p12` + `MQTT_CLIENT_KEYSTORE_PASSWORD`（口令来自 `.env`，与生成 p12 时用的同一个值）。PKCS12 里含证书链与私钥，由 `generate-certs.sh` 一并生成。
- 设备证书：`server\issue-edge-cert.ps1 -DeviceCode robot-001` 签发 `deploy/certs/edge/edge-<code>.{crt,key,p12}`（CN = 设备编号，必须与 broker 的 `user <deviceCode>` 一致），拷到边缘端后用 `--cert/--key` 连接，**不再需要 `-u/-P`**。
- 所有客户端都必须校验服务端证书：`--cafile ca.crt`（mosquitto 客户端）、`MQTT_CA_CERT`（后端）。不要在生产用 `--insecure` 或信任所有证书。

只在这一层做 TLS 校验自检（容器内执行，密码取自 `.env`）：

```powershell
# 0) 证书身份与协议：subject=CN=robot-cloud-dev / Verification: OK / Protocol: TLSv1.3
#    （mosquitto 镜像里没有 openssl CLI，用挂了同一份 certs 的 nginx 容器来验）
docker exec robot-nginx-local sh -c "openssl s_client -connect mqtt:8883 -CAfile /etc/nginx/certs/ca.crt -verify_return_error </dev/null 2>&1 | grep -E 'subject=|Verification|Protocol'"
# 1) 双向认证下用设备证书收发（exit=0）
docker exec robot-mosquitto-local mosquitto_pub -h localhost -p 8883 --cafile /mosquitto/config/certs/ca.crt --cert /mosquitto/config/certs/edge/edge-robot-001.crt --key /mosquitto/config/certs/edge/edge-robot-001.key -t robot/robot-001/telemetry -m '{"messageId":"1","deviceId":"robot-001","timestamp":"2026-01-01T00:00:00Z"}'
# 2) 不出示客户端证书被拒：error:...:SSL routines::peer did not return a certificate（exit=7）
docker exec robot-mosquitto-local mosquitto_pub -h localhost -p 8883 --cafile /mosquitto/config/certs/ca.crt -t test -m x
# 2b) 身份取自证书 CN：上面那条带 --cert 的命令不传 -u，broker 日志里应出现 u'robot-001'
docker logs --since 30s robot-mosquitto-local | Select-String 'robot-001'
# 3) 明文端口已关闭：Error: Bad file descriptor（exit=1）
docker exec robot-mosquitto-local mosquitto_pub -h localhost -p 1883 -t test -m x
# 4) 低于 TLSv1.2 被拒：SSL routines ... no protocols available
docker exec robot-nginx-local sh -c "openssl s_client -connect mqtt:8883 -CAfile /etc/nginx/certs/ca.crt -tls1_1 </dev/null 2>&1 | head -3"
```

改完证书后重建相关容器：`docker compose -f docker-compose.local.yml up -d --force-recreate mqtt nginx backend`。

## 中文与字符集

链路上四处都需要是 UTF-8，缺一处就会出现中文乱码（例如设备名称）：

- 库表：`docs/database-schema.sql` 里每个表都显式 `DEFAULT CHARSET=utf8mb4`；MySQL 容器额外传 `--character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci`。老库用 `docs/migrate-charset.sql` 补齐。
- JDBC：`DB_URL` 使用 `characterEncoding=UTF-8&connectionCollation=utf8mb4_unicode_ci`，见两个 compose 文件。
- HTTP：`application.yml` 里 `server.servlet.encoding.force=true`，保证 JSON 响应与错误信息按 UTF-8 返回。
- 脚本：`server/mock-edge.ps1` 用 `mosquitto_pub -s` 从标准输入读载荷，并把编码写成 `$global:OutputEncoding = New-Object Text.UTF8Encoding($false)`。这里必须是 `$global:`：PowerShell 5.1 只认全局作用域的 `$OutputEncoding`，在脚本作用域里赋值对原生命令的 stdin 不生效，中文会被压成 `?`（GBK/ANSI 默认编码）。另外本目录下所有 `.ps1` 都要以 **UTF-8 with BOM** 保存，否则 PowerShell 5.1 会按 ANSI 解析脚本，中文注释会吃掉换行与引号、直接语法报错。

已经写入错误字节的历史数据无法靠改配置恢复：用设备详情页的「重命名」重新写入，或参考 `docs/migrate-charset.sql` 末尾的还原语句。

## 常见问题

- 后端启动即退出：确认 compose 传给容器的是 `DB_URL`/`DB_USERNAME`/`DB_PASSWORD` 与 `MQTT_BROKER`，与 `backend/src/main/resources/application.yml` 的占位符一致。
- MQTT 收发被拒：`deploy/mosquitto/aclfile` 必须有 `user cloud-service` 段落，否则在 `allow_anonymous false` 下该账号没有任何 ACL 条目。注意双向认证开启后**用户名来自证书 CN**，传 `-u/-P` 不再改变身份；要换身份就换证书。
- MQTT 客户端连不上：先确认端口用 `8883`（宿主机 `8884`）、带 `--cafile`，并且**带上了客户端证书** `--cert/--key`——broker 已开 `require_certificate true`，不出示证书会直接 `peer did not return a certificate`（不是账号问题）。明文 1883 已经关掉了，连它会直接连接被拒。
- 后端连不上 broker / 一直重连：看后端日志里有没有 `failed to build MQTT TLS socket factory` 或 `unable to find valid certification path`。前者多半是 `cloud-service.p12` 没挂进容器、或 `MQTT_CLIENT_KEYSTORE_PASSWORD` 与生成口令不一致；后者是 CA 没挂对。
- 证书相关启动失败：`Unable to load server key file` / `error setting certificate` 说明 `deploy/certs/` 里没有证书或权限不对，重跑 `.\certs\generate-dev-certs.ps1`，并确认 compose 里 mqtt 的启动命令（拷贝 + `chown`）没被改掉。
- 浏览器提示证书无效：自签证书的预期行为，本地点「继续访问」。如果换过域名/IP 导致证书不匹配，改 `certs/openssl-san.cnf` 后重新生成并重建 mqtt/nginx。
- mosquitto 容器起不来或 MQTT 完全收不到消息：`deploy/mosquitto/` 下的 `mosquitto.conf`、`aclfile`、`passwordfile` 必须是 LF 换行且**不能带 UTF-8 BOM**。带 BOM 的 aclfile 会让 mosquitto 2.x 报 `Invalid line in acl_file "...": user` 并拒绝启动；Windows 编辑器另存为 UTF-8 时容易加上 BOM，改完请确认首字节不是 `EF BB BF`。
- 本地联调账号：`aclfile` 中 `cloud-service` 除云端规则（读 `telemetry/heartbeat/event/cmd_ack`、写 `cmd`）外，还额外放开了写 `telemetry/heartbeat/event/cmd_ack` 与读 `cmd`，供 `mock-edge.ps1` 复用同一账号模拟边缘端。生产按 `docs/mqtt-contract.md` 为每台设备分配独立账号后，可删掉这几条宽松规则。
- 设备列表为空：确认 `mock-edge.ps1` 使用的 `-DeviceId` 与页面显示的设备一致。
- 想给设备起中文名：设备总览页「注册设备」，或详情页「重命名」，不要直接用 SQL 客户端手写中文。
- 云端 MQTT 一直重连/遥测忽有忽无：先看 `docker logs --since 5m robot-backend-local | Select-String "Connection lost|malformed"`。如果刷屏，多半是有设备（或压测脚本）在持续发**坏报文**；新版本已做到「坏报文只丢帧、不断连接」，但真正的原因还是要修设备侧的载荷。用 `docker exec robot-mosquitto-local ps -ef` 能揪出容器里残留的 `mosquitto_pub` 压测进程。
- `docker exec ... mosquitto_pub -l` 只发出去一部分就结束：这是 mosquitto_pub 客户端自身在 QoS 1 下的突发限制，不是 broker 或云端丢帧。分块发布即可，判据是「broker 收到多少、云端就该入库多少」（对比 `/api/system/stats` 的 `inserted`）。
- 设备重命名后名称显示成别的文字/乱码：见上面「中文与字符集」，链路四处都要 UTF-8；历史脏数据只能重命名覆盖。
