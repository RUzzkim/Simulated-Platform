#!/usr/bin/env bash
# 端到端验收冒烟：串起「注册 → 审批 → 登录 → 下发 → 分析」整条链路，逐步打印 PASS/FAIL。
# 打本地运行栈（默认 127.0.0.1:8090）。只读为主，仅创建一个测试账号（用完置 REJECTED，不硬删，留审计）。
#
# 用法：
#   bash server/smoke-e2e.sh
#   BASE_URL=http://127.0.0.1:8090 ADMIN_USER=admin ADMIN_PASS=admin-local-pass bash server/smoke-e2e.sh
#
# 依赖：bash + curl。不依赖 jq（用 sed/grep 抠字段，够冒烟用）。

set -u

BASE_URL="${BASE_URL:-http://127.0.0.1:8090}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin-local-pass}"
TEST_USER="${TEST_USER:-smoke_$(date +%s)}"
TEST_PASS="${TEST_PASS:-smoke-pass-123456}"

pass=0
fail=0

ok()   { echo "  [PASS] $1"; pass=$((pass+1)); }
bad()  { echo "  [FAIL] $1"; fail=$((fail+1)); }
step() { echo ""; echo "== $1 =="; }

# 取 JSON 字段（字符串）：json_str '<body>' 'token'
json_str() { echo "$1" | sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p" | head -1; }
# 取 JSON 字段（数字）：json_num '<body>' 'id'
json_num() { echo "$1" | sed -n "s/.*\"$2\":\([0-9][0-9]*\).*/\1/p" | head -1; }
# 取某路径的 HTTP 状态码：http_code <method> <url> [token] [body]
http_code() {
  local method="$1" url="$2" token="${3:-}" body="${4:-}"
  local args=(-s -o /dev/null -w "%{http_code}" -X "$method" "$url")
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  if [ -n "$body" ]; then args+=(-H "Content-Type: application/json" -d "$body"); fi
  curl "${args[@]}"
}

echo "冒烟目标：$BASE_URL  管理员：$ADMIN_USER  测试账号：$TEST_USER"

# 1) 健康检查
step "1. 健康检查 GET /api/health"
code=$(http_code GET "$BASE_URL/api/health")
[ "$code" = "200" ] && ok "health 200" || bad "health 期望 200，实际 $code"

# 2) 自助注册（落 PENDING、不发令牌）
# 注意：请求体保持纯 ASCII——Git Bash（GBK locale）会把中文经 curl -d 传成坏字节，后端解析失败。
step "2. 自助注册 POST /api/auth/register"
reg=$(curl -s -X POST "$BASE_URL/api/auth/register" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$TEST_USER\",\"password\":\"$TEST_PASS\",\"displayName\":\"$TEST_USER\",\"role\":\"VIEWER\"}")
if echo "$reg" | grep -q "\"error\""; then
  bad "注册返回错误：$reg"
elif echo "$reg" | grep -q "\"status\":\"PENDING\""; then
  ok "注册已受理（PENDING、未发令牌）"
else
  bad "注册响应异常：$reg"
fi

# 3) 管理员登录
step "3. 管理员登录 POST /api/auth/login"
login=$(curl -s -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}")
ADMIN_TOKEN=$(json_str "$login" token)
if [ -n "$ADMIN_TOKEN" ]; then ok "管理员登录成功（token ${#ADMIN_TOKEN} 字符）"; else bad "管理员登录失败：$login"; fi

# 4) 待审列表里找到测试账号并审批通过
step "4. 审批 GET /api/users + POST /api/users/{id}/approve"
users=$(curl -s "$BASE_URL/api/users" -H "Authorization: Bearer $ADMIN_TOKEN")
# 抠出测试账号那段对象里的 id：先截到 username 之后再取前面最近的 id
TEST_ID=$(echo "$users" | tr '}' '\n' | grep "\"username\":\"$TEST_USER\"" | sed -n 's/.*"id":\([0-9]*\).*/\1/p' | head -1)
if [ -n "$TEST_ID" ]; then
  ok "在账号列表找到测试账号 id=$TEST_ID"
  appr_code=$(http_code POST "$BASE_URL/api/users/$TEST_ID/approve" "$ADMIN_TOKEN" '{"role":"VIEWER"}')
  [ "$appr_code" = "200" ] && ok "审批通过 200" || bad "审批期望 200，实际 $appr_code"
else
  bad "账号列表没找到 $TEST_USER"
fi

# 5) 新账号登录（审批后应能登录）
step "5. 新账号登录 POST /api/auth/login"
nlogin=$(curl -s -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$TEST_USER\",\"password\":\"$TEST_PASS\"}")
NEW_TOKEN=$(json_str "$nlogin" token)
if [ -n "$NEW_TOKEN" ]; then ok "新账号登录成功"; else bad "新账号登录失败：$nlogin"; fi

# 6) 取第一台设备
step "6. 设备列表 GET /api/devices"
devices=$(curl -s "$BASE_URL/api/devices" -H "Authorization: Bearer $ADMIN_TOKEN")
DEVICE_ID=$(json_num "$devices" id)
if [ -n "$DEVICE_ID" ]; then ok "取到设备 id=$DEVICE_ID"; else bad "无设备可测：$devices"; fi

# 7) 下发一条指令（本地无边端在线时会停在 PENDING，允许，仅校验接口可用）
# 设备类型决定合法 cmdType：边端（绑 simulationId）只认 START/STOP/MOVE_HOME/MOVE_JOINT；
# 其余设备走 PARAMETER/STRATEGY/MODEL/CONFIG。据设备详情里的 simulationId 判断。
step "7. 下发指令 POST /api/devices/{id}/commands"
if [ -n "$DEVICE_ID" ]; then
  detail=$(curl -s "$BASE_URL/api/devices/$DEVICE_ID" -H "Authorization: Bearer $ADMIN_TOKEN")
  if echo "$detail" | grep -q "\"simulationId\":\"[^\"]"; then
    body='{"cmdType":"MOVE_HOME","speed":1}'
    kind="边端(MOVE_HOME)"
  else
    body='{"cmdType":"CONFIG","version":1,"payload":{"smoke":true}}'
    kind="常规(CONFIG)"
  fi
  cmd=$(curl -s -X POST "$BASE_URL/api/devices/$DEVICE_ID/commands" -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H 'Content-Type: application/json' -d "$body")
  CMD_ID=$(json_num "$cmd" id)
  if [ -n "$CMD_ID" ]; then
    ok "下发成功 $kind command id=$CMD_ID（回执可能 PENDING，本地无边端时属正常，跳过回执校验）"
  else
    bad "下发失败：$cmd"
  fi
fi

# 8) 分析五连
step "8. 分析接口 /api/analysis/*"
if [ -n "$DEVICE_ID" ]; then
  for path in \
    "/api/analysis/health?windowHours=24" \
    "/api/analysis/devices/$DEVICE_ID/health?windowHours=24" \
    "/api/analysis/devices/$DEVICE_ID/anomalies?windowHours=24&sigma=3" \
    "/api/analysis/devices/$DEVICE_ID/trend?windowHours=24&buckets=12"; do
    code=$(http_code GET "$BASE_URL$path" "$ADMIN_TOKEN")
    [ "$code" = "200" ] && ok "GET $path 200" || bad "GET $path 期望 200，实际 $code"
  done
  if [ -n "${CMD_ID:-}" ]; then
    code=$(http_code GET "$BASE_URL/api/analysis/commands/$CMD_ID/effect?metric=effort&windowMinutes=30" "$ADMIN_TOKEN")
    [ "$code" = "200" ] && ok "GET /api/analysis/commands/$CMD_ID/effect 200" || bad "effect 期望 200，实际 $code"
  fi
fi

# 9) 清理：把测试账号驳回（不硬删，留审计）
step "9. 清理 POST /api/users/{id}/reject"
if [ -n "${TEST_ID:-}" ]; then
  # 已 APPROVED 的账号 reject 可能返回 400（只允许 PENDING→REJECTED），用停用兜底
  rej_code=$(http_code POST "$BASE_URL/api/users/$TEST_ID/reject" "$ADMIN_TOKEN")
  if [ "$rej_code" = "200" ]; then
    ok "测试账号已驳回"
  else
    dis_code=$(http_code PUT "$BASE_URL/api/users/$TEST_ID" "$ADMIN_TOKEN" '{"enabled":false}')
    [ "$dis_code" = "200" ] && ok "测试账号已停用（reject 返回 $rej_code，改用停用兜底）" \
      || bad "清理失败：reject=$rej_code disable=$dis_code（请手动处理账号 $TEST_USER）"
  fi
fi

# 汇总
echo ""
echo "================ 冒烟结果 ================"
echo "  PASS: $pass    FAIL: $fail"
if [ "$fail" -eq 0 ]; then
  echo "  ✅ 全部通过"
  exit 0
else
  echo "  ❌ 有失败项，见上方 [FAIL]"
  exit 1
fi
