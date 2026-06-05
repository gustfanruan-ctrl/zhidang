import { api } from '../api'

export async function fetchFollowupRecords(params = {}) {
  const resp = await api.get('/api/v1/followup-records', { params })
  return resp.data
}

export async function fetchFollowupRecordDetail(recordId) {
  const resp = await api.get(`/api/v1/followup-records/${recordId}`)
  return resp.data
}

export async function triggerFollowupFetch() {
  const resp = await api.post('/api/v1/followup-records/fetch')
  return resp.data
}

export async function startFollowupAnalysis(recordId) {
  const resp = await api.post(`/api/v1/transcripts/${recordId}/analyze`, null, {
    params: { source_type: 'followup' },
  })
  return resp.data
}
