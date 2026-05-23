<template>
  <Toaster />
  <div class="space-y-6">
    <div>
      <h1 class="text-xl font-bold">LLM 配置</h1>
      <p class="text-sm text-muted-foreground mt-1">管理大模型连接、提示词和超时参数</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- LLM 配置 -->
      <Card>
        <CardHeader>
          <CardTitle class="text-base">模型配置</CardTitle>
        </CardHeader>
        <CardContent class="space-y-5">
          <!-- Tab Bar -->
          <div class="flex gap-0.5 p-1 bg-muted rounded-lg">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              class="flex-1 h-8 rounded-md text-xs font-medium transition-colors"
              :class="activeTab === tab.key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'"
              @click="activeTab = tab.key"
            >{{ tab.label }}</button>
          </div>

          <!-- 通用 -->
          <div v-show="activeTab === 'general'" class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Provider</span>
              <SelectNative v-model="form.provider">
                <option value="dashscope">dashscope</option>
                <option value="openai_compatible">openai_compatible</option>
              </SelectNative>
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">LLM API Key</span>
              <Input v-model="form.api_key" type="password" :placeholder="apiKeyConfigured ? '已配置，留空不修改' : '留空不修改'" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Base URL</span>
              <Input v-model="form.base_url" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Temperature</span>
              <Input v-model.number="form.temperature" type="number" :step="0.1" :min="0" :max="1" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Max Tokens</span>
              <Input v-model.number="form.max_tokens" type="number" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Agent-A 模型</span>
              <Input v-model="form.agent_a_model" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Agent-B 模型</span>
              <Input v-model="form.agent_b_model" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">对话模型</span>
              <Input v-model="form.nl_chat_model" />
            </label>
          </div>

          <!-- Agent-A -->
          <div v-show="activeTab === 'agenta'" class="space-y-4">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Agent-A Prompt</span>
              <Textarea v-model="form.agent_a_prompt" class="min-h-[120px] font-mono text-xs" :rows="8" />
            </label>
          </div>

          <!-- Agent-B -->
          <div v-show="activeTab === 'agentb'" class="space-y-4">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Agent-B Prompt</span>
              <Textarea v-model="form.agent_b_prompt" class="min-h-[120px] font-mono text-xs" :rows="8" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">NL 查询 Prompt</span>
              <Textarea v-model="form.nl_query_prompt" class="min-h-[120px] font-mono text-xs" :rows="8" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">NL 修改 Prompt</span>
              <Textarea v-model="form.nl_modify_prompt" class="min-h-[120px] font-mono text-xs" :rows="8" />
            </label>
          </div>

          <!-- 超时 -->
          <div v-show="activeTab === 'timeout'" class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">前端请求超时(ms)</span>
              <Input v-model.number="frontendTimeoutMs" type="number" :min="5000" :max="3600000" :step="1000" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">LLM请求超时(s)</span>
              <Input v-model.number="backendTimeoutConfig.llm_request_timeout_seconds" type="number" :min="10" :max="7200" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">LLM连接超时(s)</span>
              <Input v-model.number="backendTimeoutConfig.llm_connect_timeout_seconds" type="number" :min="3" :max="7200" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Agent总超时(s)</span>
              <Input v-model.number="backendTimeoutConfig.agent_total_timeout_seconds" type="number" :min="30" :max="7200" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Tool超时(s)</span>
              <Input v-model.number="backendTimeoutConfig.agent_tool_timeout_seconds" type="number" :min="5" :max="7200" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">最大迭代轮次</span>
              <Input v-model.number="backendTimeoutConfig.agent_max_iterations" type="number" :min="1" :max="20" />
            </label>
          </div>

          <Separator />

          <div class="flex gap-3 flex-wrap">
            <Button variant="secondary" size="sm" @click="restore">恢复默认</Button>
            <Button variant="outline" size="sm" :disabled="testing" @click="test">
              <Loader2 v-if="testing" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
              {{ testing ? '测试中...' : '测试' }}
            </Button>
            <Button size="sm" :disabled="saving" @click="save">
              <Loader2 v-if="saving" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
              {{ saving ? '保存中...' : '保存配置' }}
            </Button>
          </div>

          <div class="flex gap-2">
            <Badge variant="secondary" class="text-[11px]">{{ versions.agent_a }}</Badge>
            <Badge variant="secondary" class="text-[11px]">{{ versions.agent_b }}</Badge>
          </div>
        </CardContent>
      </Card>

      <!-- 测试输出 -->
      <Card>
        <CardHeader>
          <CardTitle class="text-base">测试输出</CardTitle>
        </CardHeader>
        <CardContent>
          <pre class="whitespace-pre-wrap bg-muted text-muted-foreground p-4 rounded-lg border text-xs font-mono max-h-[70vh] overflow-auto">{{ preview || '点击"测试"查看输出' }}</pre>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Loader2 } from '@lucide/vue'
import { api, getApiTimeout, setApiTimeout, getBackendTimeoutConfig, setBackendTimeoutConfig } from '../api'
import { useToast } from '../composables/useToast'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import CardContent from '../components/ui/CardContent.vue'
import Input from '../components/ui/Input.vue'
import Textarea from '../components/ui/Textarea.vue'
import Button from '../components/ui/Button.vue'
import Badge from '../components/ui/Badge.vue'
import Separator from '../components/ui/Separator.vue'
import SelectNative from '../components/ui/SelectNative.vue'
import Toaster from '../components/ui/Toaster.vue'

const { toast } = useToast()

const tabs = [
  { key: 'general', label: '通用' },
  { key: 'agenta', label: 'Agent-A' },
  { key: 'agentb', label: 'Agent-B' },
  { key: 'timeout', label: '超时' },
]
const activeTab = ref('general')

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
    toast({ title: '保存成功', description: new Date().toLocaleTimeString(), variant: 'default' })
    await load()
  } catch (error) {
    toast({ title: '保存失败', description: toErrorText(error), variant: 'destructive' })
  } finally {
    saving.value = false
  }
}
const testing = ref(false)

async function test() {
  if (testing.value) return
  testing.value = true
  try {
    const { data } = await api.post('/api/v1/admin/llm-config/test', { target: 'agent_a', transcript_text: form.agent_a_prompt.slice(0, 80) })
    preview.value = data.preview
    toast({ title: '测试成功', variant: 'default' })
  } catch (error) {
    toast({ title: '测试失败', description: toErrorText(error), variant: 'destructive' })
  } finally {
    testing.value = false
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
