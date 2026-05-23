import { api } from '../api'

// ── 操作卡片（审核/执行） ──

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

// ── 转写管理（上传/列表/详情/分析/进度） ──

export async function uploadTranscript(files, companyNameHint) {
  const formData = new FormData()
  for (const f of files) {
    formData.append('files', f)
  }
  formData.append('company_name_hint', companyNameHint || '')
  const resp = await api.post('/api/v1/transcript/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return resp.data
}

export async function startTranscriptAnalysis(transcriptId) {
  const resp = await api.post(`/api/v1/transcripts/${transcriptId}/analyze`)
  return resp.data
}

export async function fetchTranscripts() {
  const resp = await api.get('/api/v1/transcripts')
  return resp.data
}

export async function fetchTranscriptDetail(transcriptId) {
  const resp = await api.get(`/api/v1/transcripts/${transcriptId}`)
  return resp.data
}

export async function fetchTranscriptProgress(transcriptId) {
  const resp = await api.get(`/api/v1/transcripts/${transcriptId}/progress`)
  return resp.data
}
