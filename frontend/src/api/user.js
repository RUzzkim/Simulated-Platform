import request from './request'

export const getUsers = () => request.get('/users')
export const createUser = (data) => request.post('/users', data)
export const updateUser = (id, data) => request.put(`/users/${id}`, data)
export const resetUserPassword = (id, password) => request.post(`/users/${id}/password`, { password })
export const approveUser = (id, data) => request.post(`/users/${id}/approve`, data || {})
export const rejectUser = (id) => request.post(`/users/${id}/reject`)