// CR-FINAL-FIX: 修复前端统一鉴权错误处理，补充401/403/500拦截与会话清理。
import axios from 'axios'

const TIMEOUT_KEY = 'zhidang_frontend_timeout_ms'
const BACKEND_TIMEOUTS_KEY = 'zhidang_backend_timeout_config_v1'
const DEFAULT_TIMEOUT_MS = 30000

export function getApiTimeout() {
  const raw = localStorage.getItem(TIMEOUT_KEY)
  const value = Number(raw)
  if (!Number.isFinite(value) || value < 5000) return DEFAULT_TIMEOUT_MS
  return Math.min(value, 300000)
}

export function setApiTimeout(timeoutMs) {
  const value = Number(timeoutMs)
  if (!Number.isFinite(value)) return
  const safe = Math.min(Math.max(value, 5000), 300000)
  localStorage.setItem(TIMEOUT_KEY, String(safe))
}

export function getBackendTimeoutConfig() {
  try {
    const raw = localStorage.getItem(BACKEND_TIMEOUTS_KEY)
    if (!raw) {
      return {
        llm_request_timeout_seconds: 120,
        llm_connect_timeout_seconds: 20,
        agent_total_timeout_seconds: 180,
        agent_tool_timeout_seconds: 30,
        agent_max_iterations: 8,
      }
    }
    const parsed = JSON.parse(raw)
    return {
      llm_request_timeout_seconds: Number(parsed.llm_request_timeout_seconds) || 120,
      llm_connect_timeout_seconds: Number(parsed.llm_connect_timeout_seconds) || 20,
      agent_total_timeout_seconds: Number(parsed.agent_total_timeout_seconds) || 180,
      agent_tool_timeout_seconds: Number(parsed.agent_tool_timeout_seconds) || 30,
      agent_max_iterations: Number(parsed.agent_max_iterations) || 8,
    }
  } catch {
    return {
      llm_request_timeout_seconds: 120,
      llm_connect_timeout_seconds: 20,
      agent_total_timeout_seconds: 180,
      agent_tool_timeout_seconds: 30,
      agent_max_iterations: 8,
    }
  }
}

export function setBackendTimeoutConfig(config) {
  const safe = {
    llm_request_timeout_seconds: Math.min(Math.max(Number(config.llm_request_timeout_seconds) || 120, 10), 600),
    llm_connect_timeout_seconds: Math.min(Math.max(Number(config.llm_connect_timeout_seconds) || 20, 3), 120),
    agent_total_timeout_seconds: Math.min(Math.max(Number(config.agent_total_timeout_seconds) || 180, 30), 900),
    agent_tool_timeout_seconds: Math.min(Math.max(Number(config.agent_tool_timeout_seconds) || 30, 5), 300),
    agent_max_iterations: Math.min(Math.max(Number(config.agent_max_iterations) || 8, 1), 20),
  }
  localStorage.setItem(BACKEND_TIMEOUTS_KEY, JSON.stringify(safe))
}

export const api = axios.create({ baseURL: '/', timeout: getApiTimeout() })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('zhidang_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  config.timeout = getApiTimeout()
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      localStorage.removeItem('zhidang_token')
      window.location.href = '/login'
    } else if (status === 403) {
      alert('权限不足，请联系管理员')
    } else if (status >= 500) {
      alert('系统异常，请稍后重试')
    }
    return Promise.reject(error)
  },
)
