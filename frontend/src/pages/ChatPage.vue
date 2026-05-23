<template>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 h-[calc(100vh-8rem)]">
    <!-- Left panel: Customer Profile -->
    <Card class="flex flex-col overflow-hidden">
      <CardHeader class="pb-3 border-b border-border/50">
        <div class="flex items-center justify-between">
          <CardTitle class="text-base">客户档案概览</CardTitle>
          <Button variant="outline" size="sm" :disabled="!customerStore.currentCustomer || loadingProfile" @click="loadAll">
            <Loader2 v-if="loadingProfile" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
            {{ loadingProfile ? '加载中...' : '加载档案' }}
          </Button>
        </div>
      </CardHeader>

      <CardContent v-if="!customerStore.currentCustomer" class="flex-1 flex items-center justify-center">
        <div class="text-center space-y-2">
          <User class="h-10 w-10 mx-auto text-muted-foreground/40" />
          <p class="text-sm text-muted-foreground">请先在侧边栏选择客户</p>
        </div>
      </CardContent>
      <CardContent v-else-if="!profile" class="flex-1 flex items-center justify-center">
        <div class="text-center space-y-2">
          <FileText class="h-10 w-10 mx-auto text-muted-foreground/40" />
          <p class="text-sm text-muted-foreground">未加载档案，请点击"加载档案"</p>
        </div>
      </CardContent>
      <CardContent v-else class="flex-1 flex flex-col min-h-0 p-0">
        <!-- Customer name -->
        <div class="px-5 pt-4 pb-3">
          <h3 class="text-lg font-semibold">{{ profile.comname_01 || profile.com_name || profile.company_name || '未命名客户' }}</h3>
        </div>

        <!-- Tab navigation -->
        <div class="px-5 pb-3 flex gap-1">
          <Button
            variant="ghost"
            size="sm"
            class="rounded-md text-xs h-8"
            :class="activeTab === 'basic' ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'text-muted-foreground hover:text-foreground'"
            @click="activeTab = 'basic'"
          >基本信息</Button>
          <Button
            variant="ghost"
            size="sm"
            class="rounded-md text-xs h-8"
            :class="activeTab === 'yuqi' ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'text-muted-foreground hover:text-foreground'"
            @click="activeTab = 'yuqi'"
          >预期</Button>
          <Button
            variant="ghost"
            size="sm"
            class="rounded-md text-xs h-8"
            :class="activeTab === 'changjing' ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'text-muted-foreground hover:text-foreground'"
            @click="activeTab = 'changjing'"
          >场景</Button>
        </div>

        <div class="flex-1 overflow-y-auto px-5 pb-4">
          <!-- Basic tab -->
          <div v-if="activeTab === 'basic'" class="space-y-4">
            <div class="grid grid-cols-2 gap-3">
              <div v-for="item in profileMetaGrid" :key="item.label" class="rounded-lg border border-border/60 bg-muted/30 p-3">
                <div class="text-[11px] text-muted-foreground mb-0.5">{{ item.label }}</div>
                <div class="text-sm font-medium">{{ item.value }}</div>
              </div>
            </div>
            <Separator />
            <div>
              <h4 class="text-sm font-semibold mb-3">更多字段</h4>
              <div class="space-y-2">
                <div v-for="(value, key) in readableProfile" :key="key" class="flex gap-3 py-1.5 border-b border-border/40 last:border-0">
                  <span class="text-xs font-medium text-muted-foreground shrink-0 w-[140px]">{{ key }}</span>
                  <pre class="text-xs whitespace-pre-wrap break-all font-sans m-0 text-foreground/80">{{ formatValue(value) }}</pre>
                </div>
              </div>
            </div>
          </div>

          <!-- Yuqi tab -->
          <div v-else-if="activeTab === 'yuqi'" class="space-y-3">
            <div class="flex items-center justify-between text-sm">
              <span class="font-medium">共 <Badge variant="secondary" class="ml-1">{{ yuqiCards.length }}</Badge> 条</span>
            </div>
            <div v-if="!yuqiCards.length" class="text-center py-8 text-sm text-muted-foreground">暂无预期数据</div>
            <Card v-for="(item, idx) in yuqiCards" :key="idx" class="p-4 bg-muted/20 border-border/50">
              <div class="flex items-start justify-between gap-2 mb-2">
                <p class="text-sm font-semibold break-words flex-1">{{ item.title }}</p>
                <Badge variant="outline" class="text-[10px] shrink-0 bg-amber-50 text-amber-700 border-amber-200">{{ item.status }}</Badge>
              </div>
              <p class="text-xs text-muted-foreground whitespace-pre-wrap break-words mb-3">{{ item.detail }}</p>
              <div class="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                <span>预计启动：{{ item.startTime }}</span>
                <span>提交人：{{ item.creator }}</span>
                <span>{{ item.createTime }}</span>
              </div>
            </Card>
          </div>

          <!-- Changjing tab -->
          <div v-else class="space-y-3">
            <div class="flex items-center justify-between text-sm">
              <span class="font-medium">共 <Badge variant="secondary" class="ml-1">{{ changjingCards.length }}</Badge> 条</span>
            </div>
            <div v-if="!changjingCards.length" class="text-center py-8 text-sm text-muted-foreground">暂无场景数据</div>
            <Card v-for="(item, idx) in changjingCards" :key="idx" class="p-4 bg-muted/20 border-border/50">
              <p class="text-sm font-semibold break-words mb-2">{{ item.title }}</p>
              <div class="mb-2">
                <div class="text-[10px] text-muted-foreground mb-0.5">业务诉求/痛点</div>
                <p class="text-xs whitespace-pre-wrap break-words">{{ item.problem }}</p>
              </div>
              <div class="mb-2">
                <div class="text-[10px] text-muted-foreground mb-0.5">核心指标/解决方案</div>
                <p class="text-xs whitespace-pre-wrap break-words">{{ item.solution }}</p>
              </div>
              <div class="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                <span>提交人：{{ item.creator }}</span>
                <span>{{ item.createTime }}</span>
              </div>
            </Card>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- Right panel: Chat -->
    <Card class="flex flex-col overflow-hidden">
      <CardHeader class="pb-3 border-b border-border/50">
        <CardTitle class="text-base">智能助手</CardTitle>
      </CardHeader>

      <!-- Messages area -->
      <div class="flex-1 overflow-y-auto p-4 space-y-4" ref="chatLogEl">
        <div v-if="!messages.length && customerStore.currentCustomer" class="flex items-center justify-center h-full">
          <div class="text-center space-y-2">
            <MessageSquare class="h-10 w-10 mx-auto text-muted-foreground/40" />
            <p class="text-sm text-muted-foreground">输入指令开始对话</p>
            <p class="text-xs text-muted-foreground/60">支持查询、新增、修改、删除操作</p>
          </div>
        </div>
        <div v-if="!customerStore.currentCustomer" class="flex items-center justify-center h-full">
          <div class="text-center space-y-2">
            <User class="h-10 w-10 mx-auto text-muted-foreground/40" />
            <p class="text-sm text-muted-foreground">请先在侧边栏选择客户</p>
          </div>
        </div>

        <div v-for="(item, idx) in messages" :key="idx" class="flex" :class="item.role === 'user' ? 'justify-end' : 'justify-start'">
          <div
            :class="item.role === 'user'
              ? 'bg-primary text-primary-foreground rounded-2xl rounded-br-md px-4 py-2.5 max-w-[80%]'
              : 'bg-muted rounded-2xl rounded-bl-md px-4 py-2.5 max-w-[80%]'"
          >
            <div class="text-[11px] font-semibold mb-1 opacity-70">{{ item.role === 'user' ? '我' : '助手' }}</div>
            <div class="text-sm whitespace-pre-wrap break-words">{{ item.text }}</div>
          </div>
        </div>

        <!-- Confirmation banner -->
        <div v-if="needsConfirm" class="flex justify-center">
          <Alert class="max-w-[85%] border-amber-200 bg-amber-50 text-amber-800">
            <AlertTriangle class="h-4 w-4" />
            <AlertTitle class="text-sm">待确认操作</AlertTitle>
            <AlertDescription class="text-xs">以上修改将应用到客户档案，确认后请点击"确认执行"</AlertDescription>
          </Alert>
        </div>
      </div>

      <!-- Input area -->
      <div class="border-t border-border/50 p-4">
        <div class="flex gap-2">
          <Input
            v-model="input"
            class="flex-1"
            placeholder="输入查询/新增/修改/删除指令"
            :disabled="sending"
            @keyup.enter="send(false)"
          />
          <Button :disabled="sending || !input.trim()" size="sm" @click="send(false)">
            <Send v-if="!sending" class="h-4 w-4" />
            <Loader2 v-else class="h-4 w-4 animate-spin" />
          </Button>
          <Button
            variant="default"
            size="sm"
            :disabled="!needsConfirm || sending"
            class="bg-emerald-600 hover:bg-emerald-700 text-white"
            @click="send(true)"
          >
            <Check v-if="!sending" class="h-4 w-4 mr-1" />
            <Loader2 v-else class="h-4 w-4 mr-1 animate-spin" />
            确认执行
          </Button>
        </div>
      </div>
    </Card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Loader2, User, FileText, MessageSquare, Send, Check, AlertTriangle } from '@lucide/vue'
import { api } from '../api'
import { getChangjingList, getCustomerProfile, getYuqiList } from '../api/customer'
import { useCustomerStore } from '../stores/customer'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import CardContent from '../components/ui/CardContent.vue'
import Button from '../components/ui/Button.vue'
import Input from '../components/ui/Input.vue'
import Badge from '../components/ui/Badge.vue'
import Separator from '../components/ui/Separator.vue'
import Alert from '../components/ui/Alert.vue'
import AlertTitle from '../components/ui/AlertTitle.vue'
import AlertDescription from '../components/ui/AlertDescription.vue'

const customerStore = useCustomerStore()
const profile = ref(null)
const yuqiList = ref([])
const changjingList = ref([])
const activeTab = ref('basic')
const input = ref('')
const messages = ref([])
const chatLogEl = ref(null)
function safeUUID() {
  try { return crypto.randomUUID() } catch { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random()*16|0; return (c==='x'?r:r&0x3|0x8).toString(16) }) }
}
const chatSessionId = ref(safeUUID())
const needsConfirm = ref(false)
const loadingProfile = ref(false)
const sending = ref(false)

const profileMetaGrid = computed(() => {
  const p = profile.value || {}
  return [
    { label: '客户层级', value: formatValue(p.level) },
    { label: 'TOP客群分类', value: formatValue(p.top_type) },
    { label: '维保客群分类', value: formatValue(p.maintenance_type) },
    { label: '年费客群分类', value: formatValue(p.annual_type) },
    { label: '公司类型', value: formatValue(p.com_type) },
    { label: '客户成功', value: formatUserName(p.success) },
    { label: '责任销售', value: formatUserName(p.com_salesman) },
    { label: '责任PM', value: formatUserName(p.com_pm) },
  ]
})

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function formatUserName(userObj) {
  if (!userObj) return '-'
  if (typeof userObj === 'string') return userObj || '-'
  return userObj.name || userObj.username || '-'
}

function formatDateTime(value) {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return String(value)
  return dt.toLocaleString('zh-CN', { hour12: false })
}

const readableProfile = computed(() => {
  const raw = profile.value || {}
  return Object.fromEntries(
    Object.entries(raw).filter(([k]) => !['creator', 'updater', 'deleter', 'ext'].includes(k)),
  )
})

const yuqiCards = computed(() => {
  return (yuqiList.value || []).map((item) => ({
    title: item.detail_brief || item._id || '未命名预期',
    detail: item.detail || '-',
    status: item.yuqi_status || '未知',
    startTime: formatDateTime(item.yuqi_starttime),
    creator: formatUserName(item.creator),
    createTime: formatDateTime(item.createTime),
  }))
})

const changjingCards = computed(() => {
  return (changjingList.value || []).map((item) => ({
    title: item.title || item._id || '未命名场景',
    problem: item.solve_what_ques || '-',
    solution: item.solve_what_ans || '-',
    creator: formatUserName(item.creator),
    createTime: formatDateTime(item.createTime),
  }))
})

async function loadProfile() {
  if (!customerStore.currentCustomer) return
  const data = await getCustomerProfile(customerStore.currentCustomer.company_id)
  const rawProfile = data?.profile || data || null
  profile.value = rawProfile?.data || rawProfile || null
}

async function loadAll() {
  if (!customerStore.currentCustomer || loadingProfile.value) return
  loadingProfile.value = true
  try {
    await loadProfile()
    const [yuqi, changjing] = await Promise.all([
      getYuqiList(customerStore.currentCustomer.company_id),
      getChangjingList(customerStore.currentCustomer.company_id),
    ])
    yuqiList.value = yuqi?.items || []
    changjingList.value = changjing?.items || []
  } finally {
    loadingProfile.value = false
  }
}

async function send(confirm) {
  if (sending.value) return
  if (!confirm && !input.value.trim()) return
  const text = confirm ? '确认执行' : input.value.trim()
  sending.value = true
  try {
    messages.value.push({ role: 'user', text })
    const { data } = await api.post('/api/v1/chat', {
      message: text,
      company_id: customerStore.currentCustomer?.company_id || null,
      session_id: chatSessionId.value,
      confirm,
    }, { timeout: 300000 })
    messages.value.push({ role: 'assistant', text: data.reply })
    chatSessionId.value = data.session_id || chatSessionId.value
    needsConfirm.value = !!data.needs_confirmation
    if (data.refresh_profile) await loadAll()
    if (!confirm) input.value = ''
  } finally {
    sending.value = false
  }
}

watch(() => customerStore.resetVersion, () => {
  messages.value = []
  input.value = ''
  needsConfirm.value = false
  profile.value = null
  yuqiList.value = []
  changjingList.value = []
  chatSessionId.value = safeUUID()
})

onMounted(async () => {
  await customerStore.fetchCustomers()
  customerStore.hydrateCurrentCustomer()
})
</script>
