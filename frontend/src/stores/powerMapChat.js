import { defineStore } from 'pinia'
import { commitChatV2, discardChatV2, startChatV2 } from '../services/powerMapChatV2'
import { useToast } from '../composables/useToast'

function makeAssistantMessage() {
  return {
    role: 'assistant',
    content: '',
    toolCalls: [],
    graphState: null,
    screenshotUrl: null,
    sandboxUrl: null,
    done: null,
    createdAt: Date.now(),
  }
}

function mapDoneError(code) {
  if (!code) return ''
  if (typeof code === 'string' && code.startsWith('vision_call_failed_round')) {
    return 'AI 服务暂时不可用，请稍后重试'
  }
  switch (code) {
    case 'llm_client_unavailable':
      return 'AI 模型未配置'
    case 'playwright_unavailable':
      return '沙箱渲染服务不可用'
    case 'fetch_failed':
      return '无法获取当前组织架构'
    case 'screenshot_failed':
      return '沙箱截图失败'
    default:
      return String(code)
  }
}

function pickScreenshot(result) {
  if (!result || typeof result !== 'object') return null
  const candidates = [
    result.screenshot,
    result.screenshot_url,
    result.screenshot_data_url,
    result.image,
    result.data_url,
    result.url,
  ]
  for (const v of candidates) {
    if (typeof v === 'string' && v.startsWith('data:image')) return v
  }
  return null
}

export const usePowerMapChatStore = defineStore('powerMapChat', {
  state: () => ({
    currentSessionId: null,
    messages: [],
    streamingText: '',
    streamingStatus: '',
    isLoading: false,
    lastDone: null,
    lastError: '',
    lastScreenshot: null,
    sandboxUrl: '',
    commitRefreshKey: 0,
    sandboxRefreshKey: 0,
  }),
  actions: {
    reset() {
      this.currentSessionId = null
      this.messages = []
      this.streamingText = ''
      this.streamingStatus = ''
      this.isLoading = false
      this.lastDone = null
      this.lastError = ''
      this.lastScreenshot = null
      this.sandboxUrl = ''
      this.sandboxRefreshKey = 0
    },

    async sendMessage(companyId, message, { version = null } = {}) {
      if (this.isLoading) return
      const trimmed = (message || '').trim()
      if (!trimmed) return
      if (!companyId) {
        this.lastError = '请先选择客户'
        return
      }

      this.messages.push({
        role: 'user',
        content: trimmed,
        toolCalls: [],
        graphState: null,
        screenshotUrl: null,
        createdAt: Date.now(),
      })

      const assistant = makeAssistantMessage()
      this.messages.push(assistant)

      this.isLoading = true
      this.streamingText = ''
      this.streamingStatus = 'AI 正在思考...'
      this.lastError = ''

      const pendingTools = new Map()
      const { toast } = useToast()

      try {
        const { sessionId, done } = await startChatV2({
          companyId,
          message: trimmed,
          version,
          onEvent: (eventType, data) => {
            switch (eventType) {
              case 'round_start': {
                if (data?.session_id) this.currentSessionId = data.session_id
                if (typeof data?.sandbox_url === 'string' && data.sandbox_url) {
                  this.sandboxUrl = data.sandbox_url
                }
                this.streamingStatus = `第 ${data?.round ?? '?'} 轮开始…`
                break
              }
              case 'thinking': {
                const chunk = data?.text_chunk || ''
                if (!chunk) break
                this.streamingText += chunk
                assistant.content += chunk
                break
              }
              case 'tool_call_start': {
                const idx = data?.index ?? 0
                pendingTools.set(idx, {
                  id: data?.id || null,
                  tool: data?.name || '',
                  args: '',
                  argsParsed: null,
                  result: null,
                })
                this.streamingStatus = `正在执行：${data?.name || '工具'}`
                break
              }
              case 'tool_call_delta': {
                const idx = data?.index ?? 0
                const entry = pendingTools.get(idx)
                if (entry) entry.args += data?.arguments || ''
                break
              }
              case 'tool_call': {
                const tool = data?.tool || ''
                const args = data?.args || {}
                this.streamingStatus = `正在执行：${tool || '工具'}`
                assistant.toolCalls.push({
                  tool,
                  args,
                  result: null,
                })
                break
              }
              case 'tool_result': {
                const tool = data?.tool || ''
                let target = null
                for (let i = assistant.toolCalls.length - 1; i >= 0; i--) {
                  const tc = assistant.toolCalls[i]
                  if (tc.tool === tool && tc.result === null) {
                    target = tc
                    break
                  }
                }
                if (!target) {
                  target = { tool, args: {}, result: null }
                  assistant.toolCalls.push(target)
                }
                target.result = data
                const shot = pickScreenshot(data)
                if (shot) {
                  assistant.screenshotUrl = shot
                  this.lastScreenshot = shot
                }
                this.streamingStatus = `${tool} 完成`
                break
              }
              case 'graph_state': {
                assistant.graphState = data
                break
              }
              case 'done': {
                this.lastDone = data
                assistant.done = data
                if (data?.session_id) this.currentSessionId = data.session_id
                if (typeof data?.sandbox_url === 'string' && data.sandbox_url) {
                  this.sandboxUrl = data.sandbox_url
                }
                if (!data?.error) this.sandboxRefreshKey += 1
                if (data?.error) {
                  const friendly = mapDoneError(data.error)
                  if (!assistant.content) assistant.content = friendly
                  this.lastError = friendly
                  toast({
                    title: 'AI 处理异常',
                    description: friendly,
                    variant: 'destructive',
                  })
                }
                this.streamingStatus = ''
                break
              }
              case 'error': {
                const msg = data?.error || data?.message || '未知错误'
                const friendly = mapDoneError(msg)
                this.lastError = friendly
                this.streamingText = `AI 服务异常：${friendly}`
                toast({
                  title: 'AI 服务异常',
                  description: friendly,
                  variant: 'destructive',
                })
                break
              }
              default:
                break
            }
          },
        })
        if (sessionId) this.currentSessionId = sessionId
        return done
      } catch (err) {
        const msg = err?.message || '网络异常，请重试'
        this.lastError = msg
        this.streamingText = `网络异常，请重试：${msg}`
        if (!assistant.content) {
          assistant.content = `请求失败：${msg}`
        }
        return null
      } finally {
        this.isLoading = false
        this.streamingText = ''
        this.streamingStatus = ''
      }
    },

    async commit(companyId) {
      if (!this.currentSessionId || !companyId) return
      if (this.isLoading) return
      const { toast } = useToast()
      const isRoundCap = this.lastDone?.exit_reason === 'max_rounds_hit'
      if (this.lastDone?.error || (this.lastDone?.converged === false && !isRoundCap)) {
        toast({
          title: '当前会话不可提交',
          description: '本轮维护未正常收敛，请先重新描述需求后再执行。',
          variant: 'destructive',
        })
        return
      }
      this.isLoading = true
      try {
        const res = await commitChatV2({ companyId, sessionId: this.currentSessionId })
        const sessionGone = res.status === 404 || res.error === 'session_not_found'
        if (sessionGone) {
          toast({ title: '会话已过期，请重新开始', variant: 'destructive' })
          this.reset()
          return
        }
        if (res.ok) {
          toast({ title: '已提交' })
          this.commitRefreshKey += 1
          this.reset()
          return
        }
        toast({
          title: '提交失败',
          description: res.error || '未知错误',
          variant: 'destructive',
        })
      } catch (err) {
        toast({
          title: '提交失败',
          description: err?.message || '网络异常',
          variant: 'destructive',
        })
      } finally {
        this.isLoading = false
      }
    },

    async discard(companyId) {
      if (!this.currentSessionId) return
      if (this.isLoading) return
      const confirmed = window.confirm('放弃当前修改？已修改的内容将不会保存')
      if (!confirmed) return
      await this.discardServer(companyId)
    },

    async discardServer(companyId) {
      const sessionId = this.currentSessionId
      this.reset()
      if (companyId && sessionId) {
        try {
          await discardChatV2({ companyId, sessionId })
        } catch {
          // best-effort — backend cleanup will hit TTL anyway
        }
      }
    },
  },
})
