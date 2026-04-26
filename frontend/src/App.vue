<template>
  <div class="shell">
    <aside v-if="isAuthed" class="sidebar">
      <div class="brand-wrap">
        <div class="brand">智档</div>
        <div class="sub">客户成功自动化</div>
      </div>

      <div class="customer-picker">
        <div class="picker-search-row">
          <input v-model="customerKeyword" class="picker-input" placeholder="搜索客户" @keyup.enter="searchCustomers" />
          <button class="picker-search-btn" :disabled="customerLoading" @click="searchCustomers">{{ customerLoading ? '搜索中...' : '搜索' }}</button>
        </div>
        <select class="picker-select" :value="selectedCustomerId" @change="onCustomerChange">
          <option value="">请选择客户</option>
          <option v-for="c in filteredCustomers" :key="c.company_id" :value="c.company_id">{{ c.company_name }}</option>
        </select>
        <button class="picker-refresh" :disabled="customerLoading" @click="refreshCustomers">{{ customerLoading ? '刷新中...' : '刷新客户' }}</button>
        <div class="picker-status" :class="{ error: !!customerWarning }">
          <span>{{ customerStatusText }}</span>
        </div>
      </div>

      <nav class="nav side-nav">
        <RouterLink v-if="isAuthed" to="/chat">💬 对话</RouterLink>
        <RouterLink v-if="isAuthed" to="/review">📋 跟进记录</RouterLink>
        <RouterLink v-if="isAuthed" to="/transcripts">📄 上传</RouterLink>
        <RouterLink v-if="isSuperadmin" to="/config">🧩 简道云配置</RouterLink>
        <RouterLink v-if="isSuperadmin" to="/llm">🧠 LLM 配置</RouterLink>
        <RouterLink v-if="isSuperadmin" to="/maintenance">🛠️ 维护</RouterLink>
      </nav>

      <div class="side-actions">
        <button class="theme-btn" @click="toggleTheme">{{ isDark ? '浅色' : '深色' }}</button>
        <button class="logout" @click="logout">退出登录</button>
      </div>
    </aside>

    <main class="main-panel" :class="{ full: !isAuthed }">
      <header class="topbar">
        <div>
          <div class="title">工作台</div>
        </div>
        <div class="user-chip">
          <strong>{{ userDisplayName || '访客' }}</strong>
          <span>{{ userRoleLabel }}</span>
        </div>
      </header>
      <section class="content">
        <RouterView />
      </section>
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from './api'
import { useCustomerStore } from './stores/customer'

const router = useRouter()
const isAuthed = ref(false)
const isSuperadmin = ref(false)
const customerStore = useCustomerStore()
const customerKeyword = ref('')
const filteredCustomers = ref([])
const selectedCustomerId = ref('')
const isDark = ref(false)
const userDisplayName = ref('')
const userRoleLabel = ref('')
const customerLoading = ref(false)
const customerWarning = ref('')
const customerStatusText = ref('未加载客户')

async function refreshAuthState() {
  const token = localStorage.getItem('zhidang_token')
  if (!token) {
    isAuthed.value = false
    isSuperadmin.value = false
    return
  }
  const me = await api.get('/api/v1/me').then((r) => r.data).catch(() => null)
  isAuthed.value = !!me
  isSuperadmin.value = me?.source === 'superadmin'
  userDisplayName.value = me?.display_name || me?.username || me?.user_name || ''
  userRoleLabel.value = me?.source === 'superadmin' ? '超级管理员' : me?.source === 'sso' ? 'SSO 用户' : '用户'
  if (isAuthed.value) {
    customerLoading.value = true
    try {
      const data = await customerStore.fetchCustomers()
      customerWarning.value = data?.warning || ''
      customerStatusText.value = `已加载 ${customerStore.customers.length} 条客户` + (customerStore.cacheTotal ? `（索引总数 ${customerStore.cacheTotal}）` : '')
    } catch (error) {
      customerWarning.value = error?.response?.data?.detail || error?.message || '客户加载失败'
      customerStatusText.value = '客户加载失败'
    } finally {
      customerLoading.value = false
    }
    customerStore.hydrateCurrentCustomer()
    filteredCustomers.value = customerStore.customers
    selectedCustomerId.value = customerStore.currentCustomer?.company_id || ''
    filterCustomers()
  }
}

function logout() {
  localStorage.removeItem('zhidang_token')
  localStorage.removeItem('zhidang_company_id')
  customerStore.clearContext()
  isAuthed.value = false
  isSuperadmin.value = false
  userDisplayName.value = ''
  userRoleLabel.value = ''
  router.push('/login')
}

function filterCustomers() {
  const k = customerKeyword.value.trim().toLowerCase()
  filteredCustomers.value = !k ? customerStore.customers : customerStore.customers.filter((c) => c.company_name.toLowerCase().includes(k))
}

async function searchCustomers() {
  const keyword = customerKeyword.value.trim()
  customerLoading.value = true
  if (!keyword) {
    try {
      const data = await customerStore.fetchCustomers(true)
      filteredCustomers.value = customerStore.customers
      customerWarning.value = data?.warning || ''
      customerStatusText.value = `已加载 ${filteredCustomers.value.length} 条客户`
    } finally {
      customerLoading.value = false
    }
    return
  }
  try {
    const data = await customerStore.fetchCustomers(true, keyword)
    // 直接信任后端返回的搜索结果，不做二次本地过滤
    filteredCustomers.value = customerStore.customers || []
    customerWarning.value = data?.warning || ''
    customerStatusText.value = `关键词 "${keyword}" 命中 ${filteredCustomers.value.length} 条`
  } catch (error) {
    console.error('客户搜索错误:', error)
    
    // 尝试获取更详细的错误信息
    let errorMessage = '搜索失败'
    if (error?.response?.data?.detail) {
      errorMessage = error.response.data.detail
    } else if (error?.response?.data?.warning) {
      errorMessage = error.response.data.warning
    } else if (error?.response?.data?.debug_info) {
      console.log('调试信息:', error.response.data.debug_info)
      if (error.response.data.debug_info.runtime_configured === false) {
        errorMessage = '简道云未配置或配置无效'
      } else if (error.response.data.debug_info.cache_items_count === 0) {
        errorMessage = '未找到匹配的客户，请检查搜索词或简道云表单数据'
      }
    }
    
    customerWarning.value = errorMessage
    customerStatusText.value = errorMessage
  } finally {
    customerLoading.value = false
  }
}

async function onCustomerChange(event) {
  const companyId = event.target.value
  selectedCustomerId.value = companyId
  const selected = customerStore.customers.find((c) => c.company_id === companyId)
  if (selected) {
    await customerStore.switchCustomer(selected, 'manual')
  } else {
    customerStore.clearContext()
  }
}

async function refreshCustomers() {
  customerLoading.value = true
  try {
    const data = await customerStore.fetchCustomers(true)
    filterCustomers()
    customerWarning.value = data?.warning || ''
    customerStatusText.value = `刷新完成，共 ${filteredCustomers.value.length} 条`
  } catch (error) {
    console.error('客户列表刷新错误:', error)
    
    // 尝试获取更详细的错误信息
    let errorMessage = '刷新失败'
    if (error?.response?.data?.detail) {
      errorMessage = error.response.data.detail
    } else if (error?.response?.data?.debug_info) {
      console.log('调试信息:', error.response.data.debug_info)
      if (error.response.data.debug_info.runtime_configured === false) {
        errorMessage = '简道云未配置或配置无效'
      } else if (error.response.data.debug_info.cache_items_count === 0) {
        errorMessage = '客户数据为空，请检查简道云表单是否有数据'
      }
    }
    
    customerWarning.value = errorMessage
    customerStatusText.value = errorMessage
  } finally {
    customerLoading.value = false
  }
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem('zhidang_theme', theme)
  isDark.value = theme === 'dark'
}

function toggleTheme() {
  applyTheme(isDark.value ? 'light' : 'dark')
}

onMounted(async () => {
  const saved = localStorage.getItem('zhidang_theme') || 'light'
  applyTheme(saved)
  await refreshAuthState()
})
router.afterEach(refreshAuthState)
</script>

<style scoped>
.shell{min-height:100vh;color:var(--text)}
.shell{display:flex}
.sidebar{
  width:260px;flex-shrink:0;min-height:100vh;padding:16px 14px;
  border-right:1px solid var(--line);background:var(--surface);
  backdrop-filter: var(--blur);-webkit-backdrop-filter: var(--blur);
  display:flex;flex-direction:column;gap:14px;
}
.brand-wrap{padding:6px 8px}
.topbar{
  position:sticky;top:0;z-index:10;
  padding:8px 12px;
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  backdrop-filter: var(--blur);
  -webkit-backdrop-filter: var(--blur);
  background: var(--surface);
  border:1px solid var(--line);
  border-radius:14px;
}
.brand{font-size:var(--fs-lg);font-weight:800;letter-spacing:.3px}
.sub{color:var(--muted)}
.title{font-size:var(--fs-md);font-weight:700}
.customer-picker{display:flex;gap:8px;align-items:center;flex-direction:column}
.picker-input,.picker-select{
  width:100%;
  padding:9px 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface-soft);color:var(--text);
}
.picker-search-row{display:flex;gap:8px;width:100%}
.picker-search-btn{
  padding:9px 12px;border-radius:12px;border:1px solid var(--line);background:var(--surface-soft);cursor:pointer;color:var(--text);white-space:nowrap
}
.picker-refresh{
  width:100%;
  padding:9px 12px;border-radius:12px;border:1px solid var(--line);background:var(--surface-soft);cursor:pointer;color:var(--text);
}
.picker-status{
  width:100%;
  font-size:12px;
  color:var(--muted);
  border:1px dashed var(--line);
  border-radius:10px;
  padding:6px 8px;
  background:var(--surface-soft);
}
.picker-status.error{color:#b91c1c;border-color:#fecaca;background:#fef2f2}
.nav{display:flex;gap:10px;flex-wrap:wrap}
.side-nav{flex-direction:column;gap:8px}
.nav a{
  color:var(--text);text-decoration:none;padding:8px 12px;border-radius:12px;background:var(--surface-soft);border:1px solid var(--line)
}
.nav a.router-link-active{background:var(--primary-weak);color:var(--primary);border-color:#bfdbfe}
.logout,.theme-btn{
  width:100%;
  color:var(--text);padding:8px 12px;border-radius:12px;background:var(--surface-soft);border:1px solid var(--line);cursor:pointer
}
.side-actions{margin-top:auto;display:grid;gap:8px}
.main-panel{flex:1;min-width:0;padding:14px;display:grid;gap:12px}
.main-panel.full{max-width:980px;margin:0 auto;width:100%}
.user-chip{
  display:grid;justify-items:end;
  padding:4px 8px;border:1px solid var(--line);border-radius:10px;background:var(--surface-soft);
}
.user-chip span{color:var(--muted)}
.content{max-width:1480px;margin:0 auto;width:100%}
@media (max-width: 980px){
  .shell{display:block}
  .sidebar{width:auto;min-height:auto;border-right:none;border-bottom:1px solid var(--line)}
}
</style>
