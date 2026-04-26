import { api } from '../api'

export async function reviewCard(data) {
  const resp = await api.post('/api/v1/operations/review', data)
  return resp.data
}

export async function executeCards(data) {
  const resp = await api.post('/api/v1/operations/execute', data)
  return resp.data
}

export async function getExecutionStatus(transcriptId) {
  const resp = await api.get(`/api/v1/operations/${transcriptId}/status`)
  return resp.data
}
