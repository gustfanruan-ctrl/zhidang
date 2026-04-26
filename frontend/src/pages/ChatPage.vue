<template>
  <div class="grid">
    <section class="card">
      <div class="head">
        <h2>📊 客户档案概览</h2>
        <button class="btn" :disabled="!customerStore.currentCustomer" @click="loadAll">加载档案</button>
      </div>
      <div v-if="!customerStore.currentCustomer" class="empty">请先在顶部选择客户</div>
      <div v-else-if="!profile" class="empty">未加载档案</div>
      <div v-else>
        <h3>{{ profile.comname_01 || profile.com_name || profile.company_name || '未命名客户' }}</h3>
        <div class="tabs">
          <button class="btn mini" :class="{ active: activeTab === 'basic' }" @click="activeTab = 'basic'">基本信息</button>
          <button class="btn mini" :class="{ active: activeTab === 'yuqi' }" @click="activeTab = 'yuqi'">预期</button>
          <button class="btn mini" :class="{ active: activeTab === 'changjing' }" @click="activeTab = 'changjing'">场景</button>
        </div>
        <div v-if="activeTab === 'basic'" class="columns one">
          <div class="profile-hero-card">
            <div class="profile-title">【{{ profile.com_name || profile.comname_01 || '未命名客户' }}】客户档案</div>
            <div class="profile-meta-grid">
              <div class="meta-item"><span>客户层级</span><strong>{{ formatValue(profile.level) }}</strong></div>
              <div class="meta-item"><span>TOP客群分类</span><strong>{{ formatValue(profile.top_type) }}</strong></div>
              <div class="meta-item"><span>维保客群分类</span><strong>{{ formatValue(profile.maintenance_type) }}</strong></div>
              <div class="meta-item"><span>年费客群分类</span><strong>{{ formatValue(profile.annual_type) }}</strong></div>
              <div class="meta-item"><span>公司类型</span><strong>{{ formatValue(profile.com_type) }}</strong></div>
              <div class="meta-item"><span>客户成功</span><strong>{{ formatUserName(profile.success) }}</strong></div>
              <div class="meta-item"><span>责任销售</span><strong>{{ formatUserName(profile.com_salesman) }}</strong></div>
              <div class="meta-item"><span>责任PM</span><strong>{{ formatUserName(profile.com_pm) }}</strong></div>
            </div>
          </div>
          <div class="detail-kv-card">
            <div class="detail-title">更多字段</div>
            <div v-for="(value, key) in readableProfile" :key="key" class="line basic-kv">
              <strong>{{ key }}</strong>
              <pre class="value-pre">{{ formatValue(value) }}</pre>
            </div>
          </div>
        </div>
        <div v-else-if="activeTab === 'yuqi'" class="columns one">
          <div class="line"><strong>数量</strong><span>{{ yuqiCards.length }}</span></div>
          <div class="card-grid">
            <article v-for="(item, idx) in yuqiCards" :key="idx" class="biz-card">
              <div class="biz-card-title">{{ item.title }}</div>
              <div class="biz-card-section">
                <div class="biz-label">预期描述</div>
                <div class="biz-content">{{ item.detail }}</div>
              </div>
              <div class="biz-card-meta">
                <span class="tag status">{{ item.status }}</span>
                <span>预计启动：{{ item.startTime }}</span>
                <span>提交人：{{ item.creator }}</span>
                <span>提交时间：{{ item.createTime }}</span>
              </div>
            </article>
          </div>
        </div>
        <div v-else class="columns one">
          <div class="line"><strong>数量</strong><span>{{ changjingCards.length }}</span></div>
          <div class="card-grid">
            <article v-for="(item, idx) in changjingCards" :key="idx" class="biz-card">
              <div class="biz-card-title">{{ item.title }}</div>
              <div class="biz-card-section">
                <div class="biz-label">业务诉求/痛点</div>
                <div class="biz-content">{{ item.problem }}</div>
              </div>
              <div class="biz-card-section">
                <div class="biz-label">核心指标/解决方案</div>
                <div class="biz-content">{{ item.solution }}</div>
              </div>
              <div class="biz-card-meta">
                <span>提交人：{{ item.creator }}</span>
                <span>提交时间：{{ item.createTime }}</span>
              </div>
            </article>
          </div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>🤖 自然语言维护</h2>
      <div class="chat-log">
        <div v-for="(item, idx) in messages" :key="idx" class="msg">
          <b>{{ item.role === 'user' ? '🧑 我' : '🤖 助手' }}：</b>{{ item.text }}
        </div>
      </div>
      <div class="row">
        <input v-model="input" class="input" placeholder="输入查询/新增/修改/删除指令" @keyup.enter="send(false)" />
        <button class="btn" @click="send(false)">发送</button>
        <button class="btn ok" :disabled="!needsConfirm" @click="send(true)">确认执行</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { getChangjingList, getCustomerProfile, getYuqiList } from '../api/customer'
import { useCustomerStore } from '../stores/customer'

const customerStore = useCustomerStore()
const profile = ref(null)
const yuqiList = ref([])
const changjingList = ref([])
const activeTab = ref('basic')
const input = ref('')
const messages = ref([])
const chatSessionId = ref(crypto.randomUUID())
const needsConfirm = ref(false)

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
  if (!customerStore.currentCustomer) return
  await loadProfile()
  const [yuqi, changjing] = await Promise.all([
    getYuqiList(customerStore.currentCustomer.company_id),
    getChangjingList(customerStore.currentCustomer.company_id),
  ])
  yuqiList.value = yuqi?.items || []
  changjingList.value = changjing?.items || []
}

async function send(confirm) {
  if (!confirm && !input.value.trim()) return
  const text = confirm ? '确认执行' : input.value.trim()
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
}

watch(() => customerStore.resetVersion, () => {
  messages.value = []
  input.value = ''
  needsConfirm.value = false
  profile.value = null
  yuqiList.value = []
  changjingList.value = []
  chatSessionId.value = crypto.randomUUID()
})

onMounted(async () => {
  await customerStore.fetchCustomers()
  customerStore.hydrateCurrentCustomer()
})
</script>

<style scoped>
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:var(--shadow)}
.card{display:flex;flex-direction:column;min-height:calc(100vh - 190px)}
.head{display:flex;justify-content:space-between;align-items:center}
.empty{color:var(--muted);padding:8px 0}
.columns{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.columns.one{grid-template-columns:1fr}
.tabs{display:flex;gap:8px;margin:10px 0}
.mini{padding:6px 10px;font-size:12px}
.mini.active{background:var(--primary);color:#fff}
.line{display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid var(--line);padding:6px 0}
.line.block{display:grid;gap:4px}
.line.basic-kv{display:grid;grid-template-columns:220px 1fr;align-items:start}
.value-pre{
  margin:0;
  white-space:pre-wrap;
  word-break:break-word;
  font-family:inherit;
  font-size:13px;
  line-height:1.5;
}
.profile-hero-card{
  border:1px solid var(--line);
  border-radius:14px;
  padding:14px;
  background:var(--surface-soft);
}
.profile-title{
  font-weight:700;
  margin-bottom:10px;
}
.profile-meta-grid{
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:10px;
}
.meta-item{
  border:1px solid var(--line);
  border-radius:10px;
  padding:8px 10px;
  background:var(--surface);
  display:grid;
  gap:4px;
}
.meta-item span{font-size:12px;color:var(--muted)}
.detail-kv-card{
  border:1px solid var(--line);
  border-radius:14px;
  padding:12px;
  background:var(--surface);
}
.detail-title{
  font-weight:700;
  margin-bottom:8px;
}
.card-grid{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:12px;
}
.biz-card{
  border:1px solid var(--line);
  border-radius:14px;
  padding:12px;
  background:var(--surface-soft);
  display:grid;
  gap:10px;
}
.biz-card-title{
  font-size:18px;
  font-weight:700;
}
.biz-card-section{display:grid;gap:6px}
.biz-label{font-size:13px;color:var(--muted)}
.biz-content{font-size:15px;line-height:1.6;white-space:pre-wrap}
.biz-card-meta{
  display:flex;
  flex-wrap:wrap;
  gap:8px 12px;
  font-size:12px;
  color:var(--muted);
}
.tag.status{
  background:#fef3c7;
  color:#b45309;
  border-radius:999px;
  padding:2px 8px;
}
.chat-log{flex:1;min-height:340px;overflow:auto;border:1px solid var(--line);border-radius:12px;padding:10px;margin-bottom:10px;background:var(--surface-soft)}
.row{display:flex;gap:8px}
.input{flex:1;padding:10px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--text)}
.btn{padding:10px 14px;border:0;border-radius:12px;background:var(--surface-soft);color:var(--text);cursor:pointer}
.ok{background:var(--ok);color:#fff}
@media (max-width: 1100px){
  .grid{grid-template-columns:1fr}
  .card-grid{grid-template-columns:1fr}
  .profile-meta-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
</style>
