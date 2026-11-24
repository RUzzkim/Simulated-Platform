import request from './request'

// 参数（按设备）
export const getParameters = (deviceId, params) => request.get(`/devices/${deviceId}/parameters`, { params })
export const createParameter = (deviceId, payload) =>
  request.post(`/devices/${deviceId}/parameters`, { payload })
export const getParameter = (deviceId, version) => request.get(`/devices/${deviceId}/parameters/${version}`)
export const publishParameter = (deviceId, version) =>
  request.post(`/devices/${deviceId}/parameters/${version}/publish`)

// 模型（按设备 + 模型名）
export const getModels = (deviceId, params) => request.get(`/devices/${deviceId}/models`, { params })
export const createModel = (deviceId, data) => request.post(`/devices/${deviceId}/models`, data)
export const publishModel = (deviceId, modelName, version) =>
  request.post(`/devices/${deviceId}/models/${modelName}/${version}/publish`)

// 策略（全局定义，下发到具体设备）
export const getStrategies = (params) => request.get('/strategies', { params })
export const createStrategy = (data) => request.post('/strategies', data)
export const getStrategy = (name, version) => request.get(`/strategies/${name}/${version}`)
export const publishStrategy = (deviceId, name, version) =>
  request.post(`/devices/${deviceId}/strategies/${name}/${version}/publish`)

// 当前生效（边缘端同时通过 GET /api/edge/publishables 拉同一份数据）
export const getPublishables = (deviceId) => request.get(`/devices/${deviceId}/publishables`)

// 归档后的小时桶
export const getHourlyTelemetry = (deviceId, params) =>
  request.get(`/devices/${deviceId}/telemetry/hourly`, { params })