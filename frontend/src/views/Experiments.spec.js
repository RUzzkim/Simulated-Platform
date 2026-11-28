// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h } from 'vue'

// mock 数据访问层与副作用模块，聚焦组件自身行为
const api = vi.hoisted(() => ({
  getExperimentRuns: vi.fn(),
  getExperimentRun: vi.fn(),
  getExperimentEvents: vi.fn(),
  getExperimentSeries: vi.fn(),
  exportExperimentRun: vi.fn(),
}))
vi.mock('@/api/experiment', () => api)

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }))
vi.mock('@/lib/toast', () => ({ toast }))

const Experiments = (await import('@/views/Experiments.vue')).default

const RUN_ID = 'a'.repeat(32)
const runRow = {
  run_id: RUN_ID,
  status: 'RECOVERED',
  strategy: 'v2',
  algorithm_version: 'v2.0.0',
  started_at_ms: 1732000000000,
  scenario: { scenario_id: 'sc-1', split: 'validation', seed: 300 },
  task: { status: 'RECOVERED', final_ee_error_m: 0.001 },
  fault: { type: 'JOINT_LOCKED', joint_index: 0, detection_latency_ms: 65 },
}
const runDetail = {
  ...runRow,
  simulation: { simulation_id: 'SIM-001', robot_id: 'edge-SIM-001', plant: 'gazebo', control_hz: 50, duration_s: 8 },
  reachability: { status: 'REACHABLE' },
  decision: { action: 'RECOVER', reason: 'TARGET_REACHED' },
  trace: { path: '/tmp/trace.jsonl', frame_count: 400, sample_rate_hz: 50, sha256: 'b'.repeat(64) },
}
// 乱序返回，验证详情时间线按仿真时间升序排序
const evtLate = {
  event_type: 'DECISION', sim_time_s: 2.0, timestamp: 1732000002000,
  fault_type: 'JOINT_LOCKED', joint_index: 0, action: 'RECOVER', reason: 'TARGET_REACHED', reachability_status: 'REACHABLE',
}
const evtEarly = { event_type: 'FAULT_INJECTED', sim_time_s: 1.0, timestamp: 1732000001000, fault_type: 'JOINT_LOCKED', joint_index: 0 }

// 用渲染函数 stub（避免运行时模板编译依赖），Dialog 仅在 open 时渲染内容
const slot = (tag = 'div') => ({ setup: (_, { slots }) => () => h(tag, slots.default ? slots.default() : []) })
const stubs = {
  Dialog: { props: ['open'], setup: (props, { slots }) => () => (props.open ? h('div', slots.default ? slots.default() : []) : null) },
  DialogContent: slot(),
  DialogHeader: slot(),
  DialogTitle: slot('h2'),
  DialogDescription: slot('p'),
  Select: slot(),
  SelectTrigger: slot(),
  SelectContent: slot(),
  SelectItem: slot(),
  SelectValue: slot(),
}

let wrapper

beforeEach(async () => {
  vi.clearAllMocks()
  // jsdom 未实现 createObjectURL，导出链路需要
  URL.createObjectURL = vi.fn(() => 'blob:mock')
  URL.revokeObjectURL = vi.fn()

  api.getExperimentRuns.mockResolvedValue({ data: { items: [runRow], total: 1, page: 0, size: 20 } })
  api.getExperimentRun.mockResolvedValue({ data: runDetail })
  api.getExperimentEvents.mockResolvedValue({ data: [evtLate, evtEarly] })
  api.getExperimentSeries.mockResolvedValue({ data: [] }) // 空序列：renderChart 早退，绕过 echarts
  api.exportExperimentRun.mockResolvedValue({ data: new Blob(['{}']) })

  wrapper = mount(Experiments, { global: { stubs } })
  await flushPromises()
  await wrapper.find('tbody tr').trigger('click') // 打开详情
  await flushPromises()
  await flushPromises()
})

afterEach(() => {
  wrapper.unmount()
  vi.restoreAllMocks()
})

describe('实验详情页', () => {
  it('打开详情时并发拉取运行/事件/曲线，并渲染标题', () => {
    expect(api.getExperimentRun).toHaveBeenCalledWith(RUN_ID)
    expect(api.getExperimentEvents).toHaveBeenCalledWith(RUN_ID)
    expect(api.getExperimentSeries).toHaveBeenCalledWith(RUN_ID, { limit: 800, downsample: false })
    // 详情 Dialog 打开并渲染运行元数据（轨迹 SHA-256 为详情独有，列表行不展示）
    expect(wrapper.text()).toContain('实验回放')
    expect(wrapper.text()).toContain('b'.repeat(64))
  })

  it('事件时间线按仿真时间升序排序', () => {
    const html = wrapper.html()
    const early = html.indexOf('1.00 s')
    const late = html.indexOf('2.00 s')
    expect(early).toBeGreaterThanOrEqual(0)
    expect(late).toBeGreaterThanOrEqual(0)
    expect(early).toBeLessThan(late)
  })
})

describe('实验导出', () => {
  it('导出 JSON：调用 export 接口并以 .json 文件名触发下载', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const appendSpy = vi.spyOn(document.body, 'appendChild')
    const btn = wrapper.findAll('button').find((b) => b.text().includes('导出 JSON'))
    expect(btn).toBeTruthy()
    await btn.trigger('click')
    await flushPromises()

    expect(api.exportExperimentRun).toHaveBeenCalledWith(RUN_ID, 'json')
    const link = appendSpy.mock.calls.at(-1)[0]
    expect(link.download).toBe(`${RUN_ID}.json`)
    expect(clickSpy).toHaveBeenCalled()
  })

  it('导出事件 CSV：以 -events.csv 文件名触发下载', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const appendSpy = vi.spyOn(document.body, 'appendChild')
    const btn = wrapper.findAll('button').find((b) => b.text().includes('导出事件 CSV'))
    expect(btn).toBeTruthy()
    await btn.trigger('click')
    await flushPromises()

    expect(api.exportExperimentRun).toHaveBeenCalledWith(RUN_ID, 'csv')
    const link = appendSpy.mock.calls.at(-1)[0]
    expect(link.download).toBe(`${RUN_ID}-events.csv`)
    expect(clickSpy).toHaveBeenCalled()
  })
})
