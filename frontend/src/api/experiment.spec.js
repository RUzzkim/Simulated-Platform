import { describe, expect, it, vi } from 'vitest'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('./request', () => ({ default: { get } }))

const {
  getExperimentRuns,
  getExperimentRun,
  getExperimentEvents,
  getExperimentSeries,
  exportExperimentRun,
} = await import('./experiment')

describe('experiment API', () => {
  it('按分页/筛选参数查询 Run 列表', () => {
    const params = { page: 0, size: 10, status: 'INCOMPLETE' }
    getExperimentRuns(params)
    expect(get).toHaveBeenCalledWith('/experiments/runs', { params })
  })

  it('透传数据分组 split 筛选参数', () => {
    const params = { page: 0, size: 20, split: 'validation' }
    getExperimentRuns(params)
    expect(get).toHaveBeenCalledWith('/experiments/runs', { params })
  })

  it('按 run_id 查询 Run 详情', () => {
    getExperimentRun('a'.repeat(32))
    expect(get).toHaveBeenCalledWith(`/experiments/runs/${'a'.repeat(32)}`)
  })

  it('按 run_id 查询故障/决策事件', () => {
    getExperimentEvents('b'.repeat(32))
    expect(get).toHaveBeenCalledWith(`/experiments/runs/${'b'.repeat(32)}/events`)
  })

  it('按 run_id 查询曲线并透传采样参数', () => {
    const params = { limit: 800, downsample: false }
    getExperimentSeries('c'.repeat(32), params)
    expect(get).toHaveBeenCalledWith(`/experiments/runs/${'c'.repeat(32)}/series`, { params })
  })

  it('按 run_id 导出归档，默认 JSON 且按二进制接收', () => {
    exportExperimentRun('d'.repeat(32))
    expect(get).toHaveBeenCalledWith(`/experiments/runs/${'d'.repeat(32)}/export`, {
      params: { format: 'json' },
      responseType: 'blob',
    })
  })

  it('导出事件 CSV 时透传 format', () => {
    exportExperimentRun('e'.repeat(32), 'csv')
    expect(get).toHaveBeenCalledWith(`/experiments/runs/${'e'.repeat(32)}/export`, {
      params: { format: 'csv' },
      responseType: 'blob',
    })
  })
})
