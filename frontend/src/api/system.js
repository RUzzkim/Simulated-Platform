import request from './request'

export const getSystemStats = () => request.get('/system/stats')

// 遥测归档：dryRun 只统计，retentionDays 指定保留多少天明细（仅 ADMIN 可触发真删）
export const runArchive = (params) => request.post('/system/archive', null, { params })