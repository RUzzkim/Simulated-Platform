import request from './request'

export const getCredentials = (deviceId) => request.get(`/devices/${deviceId}/credentials`)
export const issueCredentials = (deviceId) => request.post(`/devices/${deviceId}/credentials`)
export const revokeCredentials = (deviceId) => request.delete(`/devices/${deviceId}/credentials`)