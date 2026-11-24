import request from './request'

export const getAuditLogs = (params) => request.get('/audit-logs', { params })
export const getAuditActions = () => request.get('/audit-logs/actions')