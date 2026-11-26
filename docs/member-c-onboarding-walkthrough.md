# 组 C 新人复现走查（验收标准 1）

- 目的：验证「新成员按文档可在 Docker 环境启动仿真与边缘闭环并复现一个基准卡滞场景」
- 走查日期：2026-11-26
- 环境：Windows + Docker Desktop、Python 3.14、仓库分支 `develop-C`
- 结论：**通过**。空环境起栈 → 一键演示 → 云端核对全链路成功，记录 `run_id=39cfdc923bdb436b9e985ccecf1c4204`

## 1. 前置检查

```powershell
docker version                    # 引擎可用
Get-Service com.docker.service    # 必须 Running
```

若 `docker ps` 报 500 或容器停在 `Created`：先 `Start-Service com.docker.service`，再完全退出并重开 Docker Desktop。本次走查亲历此问题，详见第 5 节卡点 1。

## 2. 起本地栈

```powershell
cd deploy
docker compose -f docker-compose.local.yml down
docker compose -f docker-compose.local.yml up -d
```

实测耗时：`down` 6.5 s，`up -d` 40.5 s。

服务与端口：

| 服务 | 端口 | 用途 |
|---|---|---|
| backend | 8090 | REST API |
| nginx | 8091 / 8443 | 前端页面 |
| mosquitto | 1883 / 8884 | MQTT 明文 / mTLS |
| mysql | 内部 | 存储 |

## 3. 等待后端就绪

`up -d` 返回时后端容器已是 `running`，但 Spring Boot 尚未监听端口，直接请求会「连接被意外关闭」。轮询登录接口即可：

```powershell
$envFile = Get-Content .env
$u = ($envFile | Where-Object { $_ -match '^ADMIN_USERNAME=' }) -replace '^ADMIN_USERNAME=',''
$p = ($envFile | Where-Object { $_ -match '^ADMIN_PASSWORD=' }) -replace '^ADMIN_PASSWORD=',''
$body = @{ username = $u; password = $p } | ConvertTo-Json
for ($i = 0; $i -lt 45; $i++) {
  try { $login = Invoke-RestMethod -Uri 'http://127.0.0.1:8090/api/auth/login' `
      -Method Post -ContentType 'application/json' -Body $body -ErrorAction Stop; break }
  catch { Start-Sleep -Seconds 2 }
}
$login.token   # 有值即就绪
```

## 4. 复现基准卡滞场景

```powershell
cd ..\edge\edge_node
py -B test/experiments/live_decision_demo.py
```

期望输出（本次实测）：

```
[1/5] 边端已启动 run_id=39cfdc923bdb436b9e985ccecf1c4204
[2/5] Run 已登记为 IN_PROGRESS，发送 MOVE_JOINT
[3/5] 注入 J0 卡滞：位置锁定 + 力矩 12.5N·m
[4/5] FAULT JOINT_LOCKED joint=J0 sim_time=2.107s
[5/5] DECISION RECOVER/TARGET_REACHED reachability=REACHABLE sim_time=2.168s
      边端优雅退出，Run 状态 INCOMPLETE
DEMO PASS  run_id=39cfdc923bdb436b9e985ccecf1c4204
```

脚本自动完成：启动边端（mTLS）→ 发 `MOVE_JOINT` → 灌 J0 卡滞状态 → 订阅事件 → `CTRL_BREAK` 优雅收尾。

## 5. 云端与页面核对

API 核对（本次实测）：

| 检查项 | 结果 |
|---|---|
| Run 状态 | `INCOMPLETE` |
| 故障 | `JOINT_LOCKED` / `J0` |
| 决策 | `RECOVER` / `TARGET_REACHED` |
| 可达性 | `REACHABLE` |
| 事件 | 2 条（`FAULT`, `DECISION`） |
| 导出 JSON | 1806 B |
| 曲线点数 | 50（10 Hz × 5 s 窗口） |

页面核对：浏览器打开 `http://127.0.0.1:8091` → 登录 → 「实验回放」→ 打开该 `run_id` → 故障/决策时间线、位置/速度/力矩曲线、导出按钮均可见。

## 6. 常见卡点

| # | 现象 | 原因 | 处理 |
|---|---|---|---|
| 1 | `docker ps` 报 500、容器停在 `Created` | `com.docker.service` 被停在 Stopped，Docker Desktop 无法拉起虚拟机 | `Start-Service com.docker.service` 后重启 Docker Desktop |
| 2 | 登录接口「连接被意外关闭」 | 容器 running ≠ Spring Boot 就绪 | 轮询登录接口，别只看容器状态 |
| 3 | 边端启动报 `the following arguments are required: --config` | 入口强制要求配置文件 | `py -B -m edge_node.main --config config\edge_config.yaml` |
| 4 | 页面打开 Run 但曲线为空 | 遥测时间戳不在 Run 时间窗，或 `run_id` 选错 | 回放时以 `started_at_ms` 为时间基准；核对 `run_id` |
| 5 | Run 一直停在 `IN_PROGRESS` | 边端被强杀，未执行收尾 | 用 Ctrl+C / SIGBREAK 优雅退出，`finally` 会发 `INCOMPLETE` |

## 7. 判定

验收标准 1 通过需同时满足：

- [x] 空环境可起栈，四容器健康
- [x] 后端 API 可用（登录成功）
- [x] 一键演示输出 `DEMO PASS`
- [x] 云端可查到故障与决策，状态为 `INCOMPLETE`
- [x] 页面可见事件时间线、曲线与导出入口
