param(
  [Parameter(Mandatory = $true)][string]$DeviceCode,
  [string]$DeployDir,
  [int]$Days = 825,
  [switch]$Force
)

# 阶段 4：给一台设备签发客户端证书（broker 打开 require_certificate 后，设备连接必须出示证书）。
#   CN = 设备编号：mosquitto 配了 use_identity_as_username true 后，用户名直接取证书 CN，
#   因此签发的 CN 必须与 provision-mqtt.ps1 写进 aclfile 的 user <deviceCode> 一致。
# 产物（deploy/certs/edge/ 下，.key 是私钥，别提交）：
#   edge-<deviceCode>.crt / .key / .p12   —— 拷到边缘端，p12 给不方便用 PEM 的客户端
# 用法：
#   .\issue-edge-cert.ps1 -DeviceCode robot-001
#   .\issue-edge-cert.ps1 -DeviceCode robot-001 -Force     # 覆盖已存在的证书
$ErrorActionPreference = 'Continue'

# -File / 相对路径调用时 $PSScriptRoot 可能为空，逐级兜底，避免 Join-Path 直接报错
if (-not $DeployDir) {
  $scriptDir = $PSScriptRoot
  if (-not $scriptDir) { $scriptDir = Split-Path -Parent $PSCommandPath }
  if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
  if (-not $scriptDir) { $scriptDir = Join-Path (Get-Location) 'server' }
  $DeployDir = Join-Path $scriptDir '..\deploy'
}
$DeployDir = [IO.Path]::GetFullPath($DeployDir)

$certs = Join-Path $DeployDir "certs"
$out = Join-Path $certs "edge"
if (-not (Test-Path (Join-Path $certs "ca.crt"))) { throw "找不到 CA：$(Join-Path $certs 'ca.crt')，先生成 CA（deploy\certs\generate-dev-certs.ps1）" }
if ($DeviceCode -notmatch '^[A-Za-z0-9_.-]{1,64}$') { throw "设备编号只能是字母/数字/下划线/短横线/点：$DeviceCode" }

New-Item -ItemType Directory -Force -Path $out | Out-Null
$crt = Join-Path $out "edge-$DeviceCode.crt"
$key = Join-Path $out "edge-$DeviceCode.key"
$p12 = Join-Path $out "edge-$DeviceCode.p12"
if ((Test-Path $crt) -and -not $Force) { throw "$crt 已存在；要重新签发加 -Force（旧证书在设备上要同步替换）" }

$clientPass = if ($env:EDGE_KEYSTORE_PASSWORD) { $env:EDGE_KEYSTORE_PASSWORD } else { "robot-cloud-edge" }
$script = @"
set -e
cd /certs
base="edge-$DeviceCode"
openssl req -newkey rsa:2048 -nodes -keyout "edge/`$base.key" -out "edge/`$base.csr" -subj "/CN=$DeviceCode"
openssl x509 -req -in "edge/`$base.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out "edge/`$base.crt" -days $Days -sha256 -extfile openssl-client.cnf -extensions client_req
openssl pkcs12 -export -inkey "edge/`$base.key" -in "edge/`$base.crt" \
  -out "edge/`$base.p12" -name "$DeviceCode" -passout pass:$clientPass
rm -f "edge/`$base.csr" ca.srl
chmod 644 "edge/`$base.crt"
chmod 640 "edge/`$base.key" "edge/`$base.p12"
"@
$scriptPath = Join-Path $out "_issue.tmp.sh"
[IO.File]::WriteAllText($scriptPath, $script.Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))

docker run --rm --entrypoint sh -v "${certs}:/certs" -w /certs alpine/openssl /certs/edge/_issue.tmp.sh
$code = $LASTEXITCODE
try { [IO.File]::Delete((Join-Path $out "_issue.tmp.sh")) } catch { }
if ($code -ne 0) { throw "openssl 运行失败（exit=$code）" }

Write-Output ""
Write-Output "已签发设备证书（CN=$DeviceCode，$Days 天）："
Write-Output "  证书   : $crt"
Write-Output "  私钥   : $key"
Write-Output "  PKCS12 : $p12  (密码来自 EDGE_KEYSTORE_PASSWORD，默认 robot-cloud-edge)"
Write-Output ""
Write-Output "边缘端连接方式（mosquitto_sub/pub 或 paho）："
Write-Output "  --cafile <ca.crt> --cert edge-$DeviceCode.crt --key edge-$DeviceCode.key -p 8883"
Write-Output "  broker 打开 use_identity_as_username 后，用户名自动取证书 CN=$DeviceCode，口令随便填或留空"
Write-Output "  HTTPS 通道（/api/edge/**）仍用凭据里的 edge token：GET /api/devices/{id}/credentials"