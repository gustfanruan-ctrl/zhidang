<template>
  <div class="flex min-h-screen bg-muted/30">
    <!-- Sidebar -->
    <aside v-if="isAuthed" class="w-64 flex-shrink-0 min-h-screen border-r border-border bg-card flex flex-col">
      <!-- Logo -->
      <div class="px-5 py-5 border-b border-border/50">
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <span class="text-primary-foreground font-bold text-sm">智</span>
          </div>
          <div>
            <div class="text-base font-bold tracking-tight leading-tight">智档</div>
            <div class="text-[11px] text-muted-foreground leading-tight">客户成功自动化</div>
          </div>
        </div>
      </div>

      <!-- Customer Section -->
      <div class="px-3 py-3 border-b border-border/50 space-y-2.5">
        <div class="flex gap-2">
          <Input v-model="customerKeyword" class="flex-1 h-8 text-xs" placeholder="搜索客户" @keyup.enter="searchCustomers" />
          <Button variant="secondary" size="sm" class="h-8 text-xs shrink-0" :disabled="customerLoading" @click="searchCustomers">
            <Search class="h-3.5 w-3.5" />
          </Button>
        </div>
        <SelectNative v-model="selectedCustomerId" class="h-9 text-xs" @update:model-value="(v) => onCustomerChange({ target: { value: v } })">
          <option value="">请选择客户</option>
          <option v-for="c in filteredCustomers" :key="c.company_id" :value="c.company_id">{{ c.company_name }}</option>
        </SelectNative>
        <div class="flex gap-2">
          <Button variant="ghost" size="sm" class="flex-1 h-7 text-xs" :disabled="customerLoading" @click="refreshCustomers">
            <RefreshCw :class="['h-3 w-3 mr-1', customerLoading && 'animate-spin']" />
            {{ customerLoading ? '刷新中...' : '刷新客户' }}
          </Button>
        </div>
        <div class="text-[11px] text-muted-foreground border border-dashed border-border rounded-lg px-2.5 py-1.5 bg-muted/50" :class="{ 'text-destructive border-destructive/30 bg-destructive/5': !!customerWarning }">
          {{ customerStatusText }}
        </div>
      </div>

      <!-- Navigation -->
      <nav class="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
        <RouterLink to="/chat" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-muted text-foreground no-underline" active-class="bg-primary/10 text-primary hover:bg-primary/15">
          <MessageSquare class="h-4 w-4 shrink-0" />
          <span class="truncate">对话</span>
        </RouterLink>
        <RouterLink to="/review" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-muted text-foreground no-underline" active-class="bg-primary/10 text-primary hover:bg-primary/15">
          <FileText class="h-4 w-4 shrink-0" />
          <span class="truncate">跟进记录</span>
        </RouterLink>
        <RouterLink to="/transcripts" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-muted text-foreground no-underline" active-class="bg-primary/10 text-primary hover:bg-primary/15">
          <Upload class="h-4 w-4 shrink-0" />
          <span class="truncate">上传</span>
        </RouterLink>
        <RouterLink to="/power-map" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-muted text-foreground no-underline" active-class="bg-primary/10 text-primary hover:bg-primary/15">
          <MapIcon class="h-4 w-4 shrink-0" />
          <span class="truncate">权利地图</span>
        </RouterLink>

        <Separator v-if="isSuperadmin" class="!my-2" />

        <RouterLink v-if="isSuperadmin" to="/config" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-muted text-foreground no-underline" active-class="bg-primary/10 text-primary hover:bg-primary/15">
          <Settings class="h-4 w-4 shrink-0" />
          <span class="truncate">简道云配置</span>
        </RouterLink>
        <RouterLink v-if="isSuperadmin" to="/llm" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-muted text-foreground no-underline" active-class="bg-primary/10 text-primary hover:bg-primary/15">
          <Brain class="h-4 w-4 shrink-0" />
          <span class="truncate">LLM 配置</span>
        </RouterLink>
        <RouterLink v-if="isSuperadmin" to="/maintenance" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors hover:bg-muted text-foreground no-underline" active-class="bg-primary/10 text-primary hover:bg-primary/15">
          <Wrench class="h-4 w-4 shrink-0" />
          <span class="truncate">维护</span>
        </RouterLink>
      </nav>

      <!-- Footer -->
      <div class="px-3 py-3 border-t border-border/50 space-y-2">
        <Button variant="ghost" size="icon" class="h-8 w-8" @click="toggleTheme" :title="isDark ? '浅色模式' : '深色模式'">
          <Sun v-if="isDark" class="h-4 w-4" />
          <Moon v-else class="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" class="w-full justify-start text-muted-foreground hover:text-destructive" @click="logout">
          <LogOut class="h-4 w-4 mr-2" />
          退出登录
        </Button>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 min-w-0 flex flex-col" :class="{ 'max-w-6xl mx-auto w-full': !isAuthed }">
      <!-- Header -->
      <header v-if="isAuthed" class="sticky top-0 z-10 bg-card/80 backdrop-blur-sm border-b border-border">
        <div class="flex items-center justify-between h-14 px-6">
          <div class="flex items-center gap-3">
            <h1 class="text-sm font-semibold text-foreground">工作台</h1>
          </div>
          <div class="flex items-center gap-3">
            <div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/50 border border-border/50">
              <div class="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                <User class="h-3.5 w-3.5 text-primary" />
              </div>
              <div class="text-right leading-tight">
                <div class="text-xs font-medium">{{ userDisplayName || '访客' }}</div>
                <div class="text-[10px] text-muted-foreground">{{ userRoleLabel }}</div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <!-- Page Content -->
      <div class="flex-1 p-6">
        <RouterView />
      </div>
    </main>
    <ToastProvider />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from './api'
import { getCachedMe } from './main'
import { useCustomerStore } from './stores/customer'
import { Search, RefreshCw, Sun, Moon, LogOut, MessageSquare, FileText, Upload, Map as MapIcon, Settings, Brain, Wrench, User } from '@lucide/vue'
import Button from './components/ui/Button.vue'
import Input from './components/ui/Input.vue'
import SelectNative from './components/ui/SelectNative.vue'
import Separator from './components/ui/Separator.vue'
import ToastProvider from './components/ToastProvider.vue'

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
  const me = getCachedMe() || await api.get('/api/v1/me').then((r) => r.data).catch(() => null)
  isAuthed.value = !!me
  isSuperadmin.value = me?.source === 'superadmin'
  userDisplayName.value = me?.display_name || me?.username || me?.user_name || ''
  userRoleLabel.value = me?.source === 'superadmin' ? '超级管理员' : me?.source === 'cas' ? 'CAS 用户' : me?.source === 'sso' ? 'SSO 用户' : '用户'
  if (isAuthed.value) {
    customerLoading.value = true
    try {
      const data = await customerStore.fetchCustomers(false)
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
    const data = await customerStore.searchCustomersRemote(keyword)
    filteredCustomers.value = data.customers || []
    customerWarning.value = data?.warning || ''
    if (data.mode === 'jiandaoyun_search') {
      customerStatusText.value = `关键词 "${keyword}" 实时命中 ${filteredCustomers.value.length} 条`
    } else {
      customerStatusText.value = `关键词 "${keyword}" 命中 ${filteredCustomers.value.length} 条`
    }
  } catch (error) {
    console.error('客户搜索错误:', error)
    let errorMessage = '搜索失败'
    if (error?.response?.data?.detail) {
      errorMessage = error.response.data.detail
    } else if (error?.response?.data?.warning) {
      errorMessage = error.response.data.warning
    }
    customerWarning.value = errorMessage
    customerStatusText.value = errorMessage
    filteredCustomers.value = []
  } finally {
    customerLoading.value = false
  }
}

 async function onCustomerChange(event) {
  const companyId = event.target.value
  selectedCustomerId.value = companyId
  let selected = customerStore.customers.find((c) => c.company_id === companyId)
  if (!selected) {
    selected = filteredCustomers.value.find((c) => c.company_id === companyId)
  }
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
