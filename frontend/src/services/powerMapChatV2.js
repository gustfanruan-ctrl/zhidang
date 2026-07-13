// SSE client for /api/v1/power-map/{company_id}/chat_v2
// 用 fetch + ReadableStream 解析 SSE，因为 EventSource 不支持 POST/自定义 Header

function parseSseChunk(buffer, onEvent) {
  let consumed = 0
  while (true) {
    const sepIdx = buffer.indexOf('\n\n', consumed)
    if (sepIdx === -1) break
    const block = buffer.slice(consumed, sepIdx)
    consumed = sepIdx + 2

    let eventType = 'message'
    const dataLines = []
    for (const rawLine of block.split('\n')) {
      const line = rawLine.replace(/\r$/, '')
      if (!line || line.startsWith(':')) continue
      const colonIdx = line.indexOf(':')
      if (colonIdx === -1) continue
      const field = line.slice(0, colonIdx)
      let value = line.slice(colonIdx + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') eventType = value
      else if (field === 'data') dataLines.push(value)
    }

    if (dataLines.length === 0) continue
    const rawData = dataLines.join('\n')
    let parsed
    try {
      parsed = JSON.parse(rawData)
    } catch {
      parsed = { raw: rawData }
    }
    onEvent(eventType, parsed)
  }
  return buffer.slice(consumed)
}

/**
 * Start a chat_v2 SSE stream.
 *
 * @param {Object} options
 * @param {string} options.companyId
 * @param {string} options.message
 * @param {string|null} [options.version]
 * @param {(eventType: string, data: any) => void} options.onEvent
 * @param {AbortSignal} [options.signal]
 * @returns {Promise<{sessionId: string|null, done: any}>} resolves with last `done` event data
 */
export async function startChatV2({ companyId, message, version = null, sessionId = null, planId = null, images = [], onEvent, signal }) {
  if (!companyId) throw new Error('companyId is required')
  if (!message || !message.trim()) throw new Error('message is required')
  if (typeof onEvent !== 'function') throw new Error('onEvent callback is required')

  const token = localStorage.getItem('zhidang_token')
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const body = { message: message.trim(), confirm: false }
  if (version) body.version = version
  if (sessionId) body.session_id = sessionId
  if (planId) body.plan_id = planId
  if (Array.isArray(images) && images.length) body.images = images

  let receivedSessionId = null
  let lastDone = null

  const response = await fetch(
    `/api/v1/power-map/${encodeURIComponent(companyId)}/chat_v2`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    },
  )

  if (!response.ok) {
    let errMsg = `HTTP ${response.status}`
    try {
      const errBody = await response.json()
      errMsg = errBody?.detail || errBody?.error || errMsg
    } catch { /* ignore */ }
    throw new Error(errMsg)
  }
  if (!response.body) {
    throw new Error('response.body is null (browser does not support streaming)')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const wrappedOnEvent = (eventType, data) => {
    if (data && typeof data === 'object' && data.session_id) {
      receivedSessionId = data.session_id
    }
    if (eventType === 'done') {
      lastDone = data
    }
    try {
      onEvent(eventType, data)
    } catch (e) {
      console.error('chat_v2 onEvent handler threw:', e)
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = parseSseChunk(buffer, wrappedOnEvent)
  }
  if (buffer.length > 0) {
    parseSseChunk(buffer + '\n\n', wrappedOnEvent)
  }

  return { sessionId: receivedSessionId, done: lastDone }
}

function buildHeaders() {
  const token = localStorage.getItem('zhidang_token')
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

/**
 * Commit a chat_v2 session — writes session changes to BI and destroys the session.
 *
 * Returns a normalized result so callers can branch on session-gone vs business
 * error without having to inspect HTTP status separately.
 *
 * @returns {Promise<{status: number, ok: boolean, error: string|null, result: any}>}
 */
export async function commitChatV2({ companyId, sessionId }) {
  if (!companyId) throw new Error('companyId is required')
  if (!sessionId) throw new Error('sessionId is required')

  const response = await fetch(
    `/api/v1/power-map/${encodeURIComponent(companyId)}/commit`,
    {
      method: 'POST',
      headers: buildHeaders(),
      body: JSON.stringify({ session_id: sessionId }),
    },
  )
  let data = null
  try { data = await response.json() } catch { /* may be empty body */ }
  return {
    status: response.status,
    ok: data?.ok === true,
    error: data?.error || (response.ok ? null : data?.detail || `http_${response.status}`),
    result: data?.result ?? null,
  }
}

export async function confirmPlanChatV2({ companyId, planId }) {
  if (!companyId) throw new Error('companyId is required')
  if (!planId) throw new Error('planId is required')

  const response = await fetch(
    `/api/v1/power-map/${encodeURIComponent(companyId)}/chat_v2/confirm-plan`,
    {
      method: 'POST',
      headers: buildHeaders(),
      body: JSON.stringify({ plan_id: planId }),
    },
  )
  let data = null
  try { data = await response.json() } catch { /* may be empty body */ }
  return {
    status: response.status,
    ok: data?.ok === true,
    error: data?.error || (response.ok ? null : data?.detail || `http_${response.status}`),
    data,
  }
}

/**
 * Discard a chat_v2 session — idempotent. `keepalive` lets it survive page unload
 * (e.g. when fired from a beforeunload handler).
 */
export async function discardChatV2({ companyId, sessionId, keepalive = false }) {
  if (!companyId) throw new Error('companyId is required')
  if (!sessionId) throw new Error('sessionId is required')

  const response = await fetch(
    `/api/v1/power-map/${encodeURIComponent(companyId)}/discard`,
    {
      method: 'POST',
      headers: buildHeaders(),
      body: JSON.stringify({ session_id: sessionId }),
      keepalive,
    },
  )
  let data = null
  try { data = await response.json() } catch { /* may be empty */ }
  return { status: response.status, ok: data?.ok !== false }
}
