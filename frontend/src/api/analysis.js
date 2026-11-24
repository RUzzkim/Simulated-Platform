import request from './request'

// 机队健康总览（按综合分升序，最差在前）
export const getFleetHealth = (params) => request.get('/analysis/health', { params })
// 单设备健康评估
export const getDeviceHealth = (id, params) => request.get(`/analysis/devices/${id}/health`, { params })
// 单设备遥测异常检测
export const getDeviceAnomalies = (id, params) => request.get(`/analysis/devices/${id}/anomalies`, { params })
// 单设备趋势 / 预测性维护（每关节 effort 斜率 + 到基线上界的外推）
export const getDeviceTrend = (id, params) => request.get(`/analysis/devices/${id}/trend`, { params })
// 下发效果分析（某条下发指令生效前后 effort 对比）
export const getCommandEffect = (commandId, params) => request.get(`/analysis/commands/${commandId}/effect`, { params })
