param([int]$Days = 825)

# 用 openssl 容器生成本地开发证书，产物放在本目录（ca.key/server.key 属于敏感文件，不要提交或外发）
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot

# cloud-service.p12 的口令必须与后端 MQTT_CLIENT_KEYSTORE_PASSWORD 一致，否则后端
# 启动时报 keystore password was incorrect。未显式设置环境变量时从 deploy\.env 读取。
if (-not $env:MQTT_CLIENT_KEYSTORE_PASSWORD) {
  $envPath = Join-Path (Split-Path -Parent $dir) '.env'
  if (Test-Path $envPath) {
    $line = Get-Content $envPath |
      Where-Object { $_ -match '^\s*MQTT_CLIENT_KEYSTORE_PASSWORD\s*=' } |
      Select-Object -First 1
    if ($line) {
      $env:MQTT_CLIENT_KEYSTORE_PASSWORD = (($line -split '=', 2)[1]).Trim().Trim('"').Trim("'")
    }
  }
}

$dockerArgs = @('run', '--rm', '--entrypoint', 'sh', '-v', "${dir}:/certs", '-w', '/certs')
if ($env:MQTT_CLIENT_KEYSTORE_PASSWORD) {
  # 只传变量名，值从当前进程环境注入，避免口令出现在命令行参数里
  $dockerArgs += @('-e', 'MQTT_CLIENT_KEYSTORE_PASSWORD')
} else {
  Write-Warning '未找到 MQTT_CLIENT_KEYSTORE_PASSWORD（环境变量与 deploy\.env 都没有），将使用 generate-certs.sh 的默认口令，可能导致后端连不上 broker'
}
$dockerArgs += @('alpine/openssl', '/certs/generate-certs.sh', '/certs', "$Days")
docker @dockerArgs