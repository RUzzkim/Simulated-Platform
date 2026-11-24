param([int]$Days = 825)

# 用 openssl 容器生成本地开发证书，产物放在本目录（ca.key/server.key 属于敏感文件，不要提交或外发）
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
docker run --rm --entrypoint sh -v "${dir}:/certs" -w /certs alpine/openssl /certs/generate-certs.sh /certs $Days