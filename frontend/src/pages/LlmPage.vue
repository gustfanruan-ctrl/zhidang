<template>
  <div class="grid">
    <section class="card">
      <h2>LLM 配置</h2>
      <div class="form-grid">
        <label>Provider<select v-model="form.provider" class="input"><option value="dashscope">dashscope</option><option value="openai_compatible">openai_compatible</option></select></label>
        <label>
          LLM API Key
          <input v-model="form.api_key" class="input" type="password" :placeholder="apiKeyConfigured ? '已配置，留空不修改' : '留空不修改'" />
        </label>
        <label>Base URL<input v-model="form.base_url" class="input"></label>
        <label>Temperature<input v-model.number="form.temperature" class="input" type="number" step="0.1" min="0" max="1"></label>
        <label>Max Tokens<input v-model.number="form.max_tokens" class="input" type="number"></label>
        <label>Agent-A 模型<input v-model="form.agent_a_model" class="input"></label>
        <label>Agent-B 模型<input v-model="form.agent_b_model" class="input"></label>
        <label>对话模型<input v-model="form.nl_chat_model" class="input"></label>
        <label>前端请求超时(ms)<input v-model.number="frontendTimeoutMs" class="input" type="number" min="5000" max="300000" step="1000"></label>
        <label>LLM请求超时(s)<input v-model.number="backendTimeoutConfig.llm_request_timeout_seconds" class="input" type="number" min="10" max="600"></label>
        <label>LLM连接超时(s)<input v-model.number="backendTimeoutConfig.llm_connect_timeout_seconds" class="input" type="number" min="3" max="120"></label>
        <label>Agent总超时(s)<input v-model.number="backendTimeoutConfig.agent_total_timeout_seconds" class="input" type="number" min="30" max="900"></label>
        <label>Tool超时(s)<input v-model.number="backendTimeoutConfig.agent_tool_timeout_seconds" class="input" type="number" min="5" max="300"></label>
        <label>最大迭代轮次<input v-model.number="backendTimeoutConfig.agent_max_iterations" class="input" type="number" min="1" max="20"></label>
      </div>
      <label>Agent-A Prompt<textarea v-model="form.agent_a_prompt" class="input"></textarea></label>
      <label>Agent-B Prompt<textarea v-model="form.agent_b_prompt" class="input"></textarea></label>
      <label>NL 查询 Prompt<textarea v-model="form.nl_query_prompt" class="input"></textarea></label>
      <label>NL 修改 Prompt<textarea v-model="form.nl_modify_prompt" class="input"></textarea></label>
      <div class="row">
        <button class="btn" @click="restore">恢复默认</button>
        <button class="btn" @click="test">测试</button>
        <button class="btn ok" :disabled="saving" @click="save">{{ saving ? '保存中...' : '保存配置' }}</button>
      </div>
      <div class="msg">{{ msg }}</div>
      <div class="row"><span class="badge">{{ versions.agent_a }}</span><span class="badge">{{ versions.agent_b }}</span></div>
    </section>

    <section class="card">
      <h2>测试输出</h2>
      <pre>{{ preview }}</pre>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, getApiTimeout, setApiTimeout, getBackendTimeoutConfig, setBackendTimeoutConfig } from '../api'

const DEFAULT_A = '你是一个专业的客户成功分析师。请从以下客户拜访会议转写中提取信息。'
const DEFAULT_B = '你是一个客户档案管理专家。请将新提取的客户预期/场景与已有档案数据进行比对。'
const form = reactive({ provider: 'dashscope', api_key: '', base_url: '', agent_a_model: '', agent_b_model: '', nl_chat_model: '', temperature: 0.3, max_tokens: 4096, agent_a_prompt: '', agent_b_prompt: '', nl_query_prompt: '', nl_modify_prompt: '' })
const msg = ref('')
const preview = ref('')
const versions = reactive({ agent_a: '-', agent_b: '-' })
const LLM_FIELDS = ['provider', 'api_key', 'base_url', 'agent_a_model', 'agent_b_model', 'nl_chat_model', 'temperature', 'max_tokens', 'agent_a_prompt', 'agent_b_prompt', 'nl_query_prompt', 'nl_modify_prompt']
const saving = ref(false)
const frontendTimeoutMs = ref(getApiTimeout())
const backendTimeoutConfig = reactive(getBackendTimeoutConfig())
const apiKeyConfigured = ref(false)

function toErrorText(error) {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return error?.message || '保存失败，请检查配置后重试'
}

async function load() {
  const { data } = await api.get('/api/v1/admin/llm-config')
  for (const key of LLM_FIELDS) {
    if (key === 'api_key') continue
    form[key] = data[key]
  }
  form.api_key = ''
  apiKeyConfigured.value = Boolean(data.api_key)
  versions.agent_a = `Agent-A v${data.agent_a_prompt_version || '-'} `
  versions.agent_b = `Agent-B v${data.agent_b_prompt_version || '-'} `
}
async function save() {
  saving.value = true
  msg.value = '保存中...'
  try {
    const payload = {}
    for (const key of LLM_FIELDS) payload[key] = form[key]
    await api.put('/api/v1/admin/llm-config', payload)
    setApiTimeout(frontendTimeoutMs.value)
    setBackendTimeoutConfig(backendTimeoutConfig)
    msg.value = `保存成功（${new Date().toLocaleTimeString()}）`
    await load()
  } catch (error) {
    msg.value = `保存失败：${toErrorText(error)}`
  } finally {
    saving.value = false
  }
}
async function test() {
  try {
    const { data } = await api.post('/api/v1/admin/llm-config/test', { target: 'agent_a', transcript_text: form.agent_a_prompt.slice(0, 80) })
    preview.value = data.preview
    msg.value = '测试成功'
  } catch (error) {
    msg.value = `测试失败：${toErrorText(error)}`
  }
}
function restore() {
  form.agent_a_prompt = DEFAULT_A
  form.agent_b_prompt = DEFAULT_B
}

onMounted(async () => {
  frontendTimeoutMs.value = getApiTimeout()
  Object.assign(backendTimeoutConfig, getBackendTimeoutConfig())
  await load()
})
</script>

<style scoped>
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:var(--shadow)}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
label{display:grid;gap:6px;font-size:14px;margin-top:12px}
.input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--text)}
textarea.input{min-height:120px}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
.btn{padding:10px 14px;border-radius:12px;border:0;background:var(--surface-soft);color:var(--text);cursor:pointer}.ok{background:var(--primary);color:#fff}
.badge{display:inline-block;padding:4px 10px;border-radius:999px;background:var(--primary-weak);color:var(--primary);font-size:12px}
pre{white-space:pre-wrap;background:var(--surface-soft);color:var(--text);padding:12px;border-radius:12px;border:1px solid var(--line)}
.msg{margin-top:10px;color:var(--muted)}
@media (max-width: 1100px){.grid,.form-grid{grid-template-columns:1fr}}
</style>
