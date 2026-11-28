import request from './request'

export const getExperimentRuns = (params) => request.get('/experiments/runs', { params })
export const getExperimentRun = (runId) => request.get(`/experiments/runs/${runId}`)
export const getExperimentEvents = (runId) => request.get(`/experiments/runs/${runId}/events`)
export const getExperimentSeries = (runId, params) => request.get(`/experiments/runs/${runId}/series`, { params })
export const exportExperimentRun = (runId, format = 'json') =>
  request.get(`/experiments/runs/${runId}/export`, { params: { format }, responseType: 'blob' })
