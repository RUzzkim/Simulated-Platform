param(
  [string]$BaseUrl = "https://127.0.0.1:8443",
  [string]$AdminUser = "admin",
  [string]$AdminPassword = $env:ADMIN_PASSWORD,
  [string]$Container = "robot-mosquitto-local",
  [string]$DeployDir,
  [string]$CloudAccount = "cloud-service",
  # 边端节点编号（simulation 契约的 simulationId），逗号分隔；用于在设备还没上报前就先把边端账号写进 ACL
  [string]$Simulations = "",
  [switch]$SkipReload
)

# 把云端签发的设备接入凭据落到 Mosquitto：写 passwordfile + aclfile，然后 SIGHUP 重载。
# 权限模型（与 docs/mqtt-contract.md 一致）：
#   cloud-service：读 robot/+/telemetry|heartbeat|event|cmd_ack，写 robot/+/cmd
#   每台设备：只读自己的 robot/<code>/cmd，只写自己的 robot/<code>/{telemetry,heartbeat,event,cmd_ack}
# 用法：$env:ADMIN_PASSWORD="admin-local-pass"; .\provision-mqtt.ps1
#       .\provision-mqtt.ps1 -Simulations SIM-001     # 边端还没上报过，先把边节点账号写进 ACL

# 这里要跟原生命令（docker/curl）打交道，用 Continue + 逐步检查 $LASTEXITCODE：
# PS 5.1 会把原生命令写到 stderr 的告警包装成 NativeCommandError，Stop 模式下会直接中断脚本。
$ErrorActionPreference = 'Continue'

# curl.exe 只在 Windows 上存在；服务器（Ubuntu）跑 pwsh 时命令名是 curl。
# 直接写 curl.exe 会让 Linux 上每个请求都失败成空响应，然后被当成“没有可用凭据”退出。
$curl = if (Get-Command curl.exe -ErrorAction SilentlyContinue) { 'curl.exe' }
        elseif (Get-Command curl -ErrorAction SilentlyContinue) { 'curl' }
        else { throw '找不到 curl / curl.exe，请先安装 curl' }

# -File / 相对路径调用时 $PSScriptRoot 可能为空，逐级兜底，避免 Join-Path 直接报错
if (-not $DeployDir) {
  $scriptDir = $PSScriptRoot
  if (-not $scriptDir) { $scriptDir = Split-Path -Parent $PSCommandPath }
  if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
  if (-not $scriptDir) { $scriptDir = Join-Path (Get-Location) 'server' }
  $DeployDir = Join-Path (Join-Path $scriptDir '..') 'deploy'
}
$DeployDir = [IO.Path]::GetFullPath($DeployDir)

# 让 PowerShell 按 UTF-8 解码原生命令（curl）的输出，否则中文设备名会变成乱码
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$global:OutputEncoding = New-Object Text.UTF8Encoding($false)
if (-not $AdminPassword) { throw "请先设置 ADMIN_PASSWORD（deploy/.env 里的管理员口令）" }

$passwordFile = Join-Path $DeployDir "mosquitto\passwordfile"
$aclFile = Join-Path $DeployDir "mosquitto\aclfile"
if (-not (Test-Path $passwordFile)) { throw "找不到 $passwordFile" }

function Read-Json([string]$Text) {
  if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
  return $Text | ConvertFrom-Json
}

function Invoke-Api([string]$Method, [string]$Path, [string]$Token, [string]$Body) {
  $args = @('-s', '-k', '-X', $Method, "$BaseUrl$Path")
  if ($Token) { $args += @('-H', "Authorization: Bearer $Token") }
  if ($Body) {
    $tmp = New-TemporaryFile
    [IO.File]::WriteAllText($tmp, $Body, (New-Object Text.UTF8Encoding($false)))
    $args += @('-H', 'Content-Type: application/json', '--data-binary', "@$tmp")
    try { $raw = & $curl @args } finally { [IO.File]::Delete($tmp) }
  } else {
    $raw = & $curl @args
  }
  # 中文必须按 UTF-8 解析，否则 PowerShell 默认 ANSI 会把名称读成乱码
  return ($raw -join "`n")
}

$loginBody = @{ username = $AdminUser; password = $AdminPassword } | ConvertTo-Json -Compress
$loginResponse = Invoke-Api 'POST' '/api/auth/login' $null $loginBody
$login = Read-Json $loginResponse
if (-not $login -or -not $login.token) { throw "登录失败：$loginResponse" }
$token = $login.token
Write-Host "已登录：$($login.user.username)（$($login.user.role)）"

$devices = Read-Json (Invoke-Api 'GET' '/api/devices' $token)
$provisioned = @()
foreach ($device in $devices) {
  $raw = Invoke-Api 'GET' "/api/devices/$($device.id)/credentials" $token
  $credential = Read-Json $raw
  if (-not $credential -or -not $credential.mqttUsername) {
    Write-Warning "$($device.deviceCode) 尚未签发接入凭据，跳过（在设备详情页点「签发凭据」）"
    continue
  }
  if ($credential.status -ne 'ACTIVE') {
    Write-Warning "$($device.deviceCode) 凭据状态为 $($credential.status)，跳过"
    continue
  }
  $provisioned += $credential
}

if ($provisioned.Count -eq 0) {
  Write-Warning '没有任何可用凭据，passwordfile / aclfile 未改动'
  exit 1
}

# 1) 用一次性 mosquitto_passwd 容器写宿主机上的 passwordfile（对只读挂载的生产环境同样适用）
foreach ($item in $provisioned) {
  # 2>&1 是必须的：mosquitto_passwd 会把权限告警写到 stderr，不重定向在 Stop 模式下会当成异常中断
  $out = & docker run --rm -v "${DeployDir}:/work" eclipse-mosquitto:2 `
    mosquitto_passwd -b "/work/mosquitto/passwordfile" $item.mqttUsername $item.mqttPassword 2>&1
  if ($LASTEXITCODE -ne 0) { throw "写入 passwordfile 失败：$($item.mqttUsername)`n$($out -join "`n")" }
  Write-Host "passwordfile <- $($item.mqttUsername)"
}

# 2) 生成 aclfile
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('# 由 server/provision-mqtt.ps1 生成，请勿手工编辑（重新签发凭据后重跑该脚本）')
$lines.Add('# 云端服务账号：订阅边缘上报、下发指令')
$lines.Add("user $CloudAccount")
$lines.Add('topic read robot/+/telemetry')
$lines.Add('topic read robot/+/heartbeat')
$lines.Add('topic read robot/+/event')
$lines.Add('topic read robot/+/cmd_ack')
$lines.Add('topic write robot/+/cmd')
# 边端（simulation 契约）的主题：state/heartbeat 云端要读（入库、故障落库），
# command 云端要下发运动指令（simulation/{sim}/command，载荷对齐边端 RobotCommand）
$lines.Add('topic read simulation/+/state')
$lines.Add('topic read simulation/+/heartbeat')
$lines.Add('topic read simulation/+/command_ack')
$lines.Add('topic read simulation/+/experiment_run')
$lines.Add('topic read simulation/+/experiment_event')
$lines.Add('topic write simulation/+/command')
foreach ($item in $provisioned) {
  $code = $item.deviceCode
  $lines.Add('')
  $lines.Add("# 设备 $code")
  $lines.Add("user $($item.mqttUsername)")
  $lines.Add("topic read robot/$code/cmd")
  $lines.Add("topic write robot/$code/telemetry")
  $lines.Add("topic write robot/$code/heartbeat")
  $lines.Add("topic write robot/$code/event")
  $lines.Add("topic write robot/$code/cmd_ack")
}
# 边端节点：一件边节点 = 一个仿真实例，证书 CN = simulationId（server/issue-edge-cert.ps1 -DeviceCode SIM-001）
# 注意：PowerShell 变量名大小写不敏感，局部变量不能叫 $simulations，否则会覆盖 -Simulations 参数
$simulationList = @($devices | ForEach-Object { $_.simulationId } | Where-Object { $_ })
if ($Simulations) {
  $simulationList += @($Simulations.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
$simulationList = @($simulationList | Sort-Object -Unique)
if ($simulationList.Count -gt 0) {
  $lines.Add('')
  $lines.Add('# 边端节点：证书 CN = simulationId，身份由 use_identity_as_username 取自证书')
  foreach ($sim in $simulationList) {
    $lines.Add('')
    $lines.Add("# 边节点 $sim")
    $lines.Add("user $sim")
    $lines.Add("topic write simulation/$sim/state")
    $lines.Add("topic write simulation/$sim/heartbeat")
    $lines.Add("topic read simulation/$sim/command")
    $lines.Add("topic read simulation/$sim/config")
    # 指令回执：云端 command_log 靠它从 PENDING 置 SUCCESS/FAILED
    $lines.Add("topic write simulation/$sim/command_ack")
    # 无 ROS 2 模式下仿真端（端）与边端在同一台机器、复用同一张证书：
    # 仿真端把原始关节状态发到 sim_state，边端订阅后走同一套故障检测/容错管线
    $lines.Add("topic write simulation/$sim/sim_state")
    $lines.Add("topic read simulation/$sim/sim_state")
    # V2 实验 Run 与故障/决策事件（契约 2.0.0）
    $lines.Add("topic write simulation/$sim/experiment_run")
    $lines.Add("topic write simulation/$sim/experiment_event")
    # 边端容错时把 MOVE_JOINT_SAFE 发回同一个 command 主题给仿真端（边-端内部协议），所以它对这个主题是读+写
    $lines.Add("topic write simulation/$sim/command")
  }
}
# 防护：空的 user/topic 行会让 mosquitto 解析 ACL 失败并直接退出（实测 exit=3），
# 宁可不写也不能把 broker 写挂
$invalid = @($lines | Where-Object { $_ -match '^user\s*$' -or $_ -match '^topic\s+\S+\s*$' })
if ($invalid.Count -gt 0) {
  throw "生成的 aclfile 含空 user/topic 行，已中止写入：$($invalid -join ' / ')"
}
[IO.File]::WriteAllText($aclFile, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
Write-Host "aclfile 已更新：$aclFile（$($provisioned.Count) 台设备）"

# 3) 同步到运行中的 broker 并重载
#    注意：mosquitto.conf 指向的是容器内 /mosquitto/conf/*（启动时从挂载拷进去并 chown 的副本），
#    只改宿主机文件不会生效，必须 docker cp 进去再 SIGHUP 重载 password_file / acl_file。
$running = ((& docker ps --filter "name=^/$Container$" --format "{{.Names}}" 2>&1) -join '').Trim()
if ($SkipReload) {
  Write-Host '已跳过同步与重载（-SkipReload）：手工执行 docker cp + docker kill -s HUP'
} elseif ($running -ne $Container) {
  Write-Warning "容器 $Container 未运行，宿主机文件已更新；容器下次启动会自动生效"
} else {
  foreach ($file in @('passwordfile', 'aclfile')) {
    $source = Join-Path $DeployDir "mosquitto\$file"
    $null = & docker cp $source "${Container}:/mosquitto/conf/$file" 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Warning "docker cp $file 失败：$Container 是否为本地开发容器？" }
  }
  $null = & docker exec $Container sh -c "chown mosquitto:mosquitto /mosquitto/conf/passwordfile /mosquitto/conf/aclfile && chmod 600 /mosquitto/conf/passwordfile /mosquitto/conf/aclfile" 2>&1
  $null = & docker kill -s HUP $Container 2>&1
  if ($LASTEXITCODE -ne 0) { Write-Warning "向 $Container 发送 SIGHUP 失败，请手动执行：docker kill -s HUP $Container" }
  else { Write-Host "已同步到 $Container 并发送 SIGHUP，账号与 ACL 已重载（无需重启 broker）" }
}

Write-Host ''
Write-Host '边缘端/仿真端接入信息（edge token 用于 HTTP 通道）：'
foreach ($item in $provisioned) {
  Write-Host ("  {0,-14} MQTT {1} / {2}" -f $item.deviceCode, $item.mqttUsername, $item.mqttPassword)
  Write-Host ("  {0,-14} HTTP token {1}" -f '', $item.edgeToken)
}