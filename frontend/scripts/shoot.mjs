/*
 * 页面截图回归工具（前端「Element Plus + Tailwind/shadcn 共存」的护栏）。
 *
 * 用法：node scripts/shoot.mjs [输出目录] [页面地址] [后端地址]
 *   node scripts/shoot.mjs .shots
 *   node scripts/shoot.mjs .shots https://127.0.0.1:8443 http://127.0.0.1:8090
 *
 * 只依赖 Node 内置能力（fetch / WebSocket）与本机 Edge（可用 EDGE_PATH 覆盖），
 * 不需要装 Puppeteer。改完 vite.config/tailwind.css/组件后跑一次，
 * 和改之前的图对比，确认 Element Plus 页面没有被动到。
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const OUT = resolve(process.argv[2] || '.shots')
const BASE = process.argv[3] || 'https://127.0.0.1:8443'
const API = process.argv[4] || 'http://127.0.0.1:8090'
const USERNAME = process.env.SHOT_USERNAME || 'admin'
const PASSWORD = process.env.SHOT_PASSWORD || 'admin-local-pass'
const PORT = Number(process.env.SHOT_PORT || 9333)

// 截图路由：包含页面名 -> 路径，需要登录后才能看的页面靠下面注入的令牌
const PAGES = [
  ['login', '/login'],
  ['devices', '/'],
  ['system', '/system'],
  ['device-detail', '/devices/1'],
  ['audit-logs', '/audit-logs'],
  ['users', '/users']
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const login = await (await fetch(`${API}/api/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: USERNAME, password: PASSWORD })
})).json()
if (!login.token) throw new Error('登录失败：' + JSON.stringify(login))

mkdirSync(OUT, { recursive: true })
const profile = join(tmpdir(), `edge-shot-${Date.now()}`)
const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--ignore-certificate-errors', '--hide-scrollbars', '--window-size=1440,1000',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, 'about:blank'
], { stdio: 'ignore' })

async function devtoolsReady() {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (res.ok) return
    } catch { /* 端口还没起 */ }
    await sleep(500)
  }
  throw new Error('Edge 的 devtools 端口没起来，检查 EDGE_PATH')
}

function cdp(ws) {
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data)
    if (!msg.id || !pending.has(msg.id)) return
    const { ok, reject } = pending.get(msg.id)
    pending.delete(msg.id)
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : ok(msg.result)
  })
  return (method, params = {}) => new Promise((ok, reject) => {
    const mid = ++id
    pending.set(mid, { ok, reject })
    ws.send(JSON.stringify({ id: mid, method, params }))
  })
}

try {
  await devtoolsReady()
  const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((ok, bad) => {
    ws.addEventListener('open', ok, { once: true })
    ws.addEventListener('error', bad, { once: true })
  })
  const send = cdp(ws)
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

  // 先落到同源页面写入会话，再逐个路由截图
  await send('Page.navigate', { url: `${BASE}/login` })
  await sleep(2000)
  await send('Runtime.evaluate', {
    expression: `localStorage.setItem('robot-cloud-token', ${JSON.stringify(login.token)});
                 localStorage.setItem('robot-cloud-user', ${JSON.stringify(JSON.stringify(login.user))});`
  })

  for (const [name, path] of PAGES) {
    await send('Page.navigate', { url: BASE + path })
    await sleep(2600)
    const { result } = await send('Runtime.evaluate', {
      expression: 'JSON.stringify({ path: location.pathname, bytes: document.body.innerHTML.length })'
    })
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, 'base64'))
    console.log(`${name.padEnd(14)} ${result.value}`)
  }
  console.log('截图输出到 ' + OUT)
} finally {
  edge.kill()
  // Edge 退出时用户目录可能还占着句柄，清不掉就算了（在 %TEMP% 下）
  try {
    rmSync(profile, { recursive: true, force: true })
  } catch {
    /* ignore */
  }
}
process.exit(0)