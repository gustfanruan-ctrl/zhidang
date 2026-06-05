<template>
  <div class="max-w-4xl mx-auto space-y-6">
    <div>
      <h1 class="text-xl font-bold">维护面板</h1>
      <p class="text-sm text-muted-foreground mt-1">查看后台、LLM、简道云健康状态</p>
    </div>

    <!-- Status cards grid -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <!-- Backend -->
      <Card :class="healthItemClass(health.backend?.ok)">
        <CardHeader class="pb-2">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center">
              <Server class="h-4 w-4 text-blue-600" />
            </div>
            <CardTitle class="text-sm">后台服务</CardTitle>
          </div>
        </CardHeader>
        <CardContent class="space-y-3">
          <div class="flex items-center gap-2">
            <Badge :variant="health.backend?.ok ? 'default' : 'destructive'" class="text-[10px]">
              {{ health.backend?.ok ? '正常' : '异常' }}
            </Badge>
          </div>
          <p class="text-xs text-muted-foreground">{{ health.backend?.message || '-' }}</p>
          <div class="flex gap-2">
            <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="testing.backend" @click="runTest('backend')">
              <Loader2 v-if="testing.backend" class="h-3 w-3 mr-1 animate-spin" />
              {{ testing.backend ? '测试中...' : '健康检查' }}
            </Button>
          </div>
          <p class="text-[10px] text-muted-foreground min-h-[16px]">{{ testMessage.backend || '' }}</p>
        </CardContent>
      </Card>

      <!-- LLM -->
      <Card :class="healthItemClass(health.llm?.ok)">
        <CardHeader class="pb-2">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center">
              <Brain class="h-4 w-4 text-purple-600" />
            </div>
            <CardTitle class="text-sm">LLM 连通性</CardTitle>
          </div>
        </CardHeader>
        <CardContent class="space-y-3">
          <div class="flex items-center gap-2">
            <Badge :variant="health.llm?.ok ? 'default' : 'destructive'" class="text-[10px]">
              {{ health.llm?.ok ? '正常' : '异常' }}
            </Badge>
          </div>
          <p class="text-xs text-muted-foreground">{{ health.llm?.message || '-' }}</p>
          <div class="flex gap-2">
            <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="testing.llm" @click="runTest('llm')">
              <Loader2 v-if="testing.llm" class="h-3 w-3 mr-1 animate-spin" />
              {{ testing.llm ? '测试中...' : '测试连接' }}
            </Button>
            <Button variant="ghost" size="sm" class="h-7 text-xs" @click="goTo('/llm')">去配置</Button>
          </div>
          <p class="text-[10px] text-muted-foreground min-h-[16px]">{{ testMessage.llm || '' }}</p>
        </CardContent>
      </Card>

      <!-- Jiandaoyun -->
      <Card :class="healthItemClass(health.jiandaoyun?.ok)">
        <CardHeader class="pb-2">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
              <Database class="h-4 w-4 text-emerald-600" />
            </div>
            <CardTitle class="text-sm">简道云连通性</CardTitle>
          </div>
        </CardHeader>
        <CardContent class="space-y-3">
          <div class="flex items-center gap-2">
            <Badge :variant="health.jiandaoyun?.ok ? 'default' : 'destructive'" class="text-[10px]">
              {{ health.jiandaoyun?.ok ? '正常' : '异常' }}
            </Badge>
          </div>
          <p class="text-xs text-muted-foreground">{{ health.jiandaoyun?.message || '-' }}</p>
          <div class="flex gap-2">
            <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="testing.jiandaoyun" @click="runTest('jiandaoyun')">
              <Loader2 v-if="testing.jiandaoyun" class="h-3 w-3 mr-1 animate-spin" />
              {{ testing.jiandaoyun ? '测试中...' : '测试连接' }}
            </Button>
            <Button variant="ghost" size="sm" class="h-7 text-xs" @click="goTo('/config')">去配置</Button>
          </div>
          <p class="text-[10px] text-muted-foreground min-h-[16px]">{{ testMessage.jiandaoyun || '' }}</p>
        </CardContent>
      </Card>
    </div>

    <!-- Cache section -->
    <Card>
      <CardHeader>
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center">
            <HardDrive class="h-4 w-4 text-amber-600" />
          </div>
          <CardTitle class="text-sm">客户索引缓存</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div class="flex items-center justify-between gap-4">
          <span class="text-sm text-muted-foreground">{{ cacheStatus }}</span>
          <Button variant="outline" size="sm" :disabled="refreshingCache" @click="refreshCache">
            <RefreshCw :class="['h-3.5 w-3.5 mr-1.5', refreshingCache && 'animate-spin']" />
            {{ refreshingCache ? '刷新中...' : '强制刷新索引' }}
          </Button>
        </div>
      </CardContent>
    </Card>

    <!-- Footer -->
    <div class="flex items-center justify-between text-xs text-muted-foreground px-1">
      <span>总状态：<span :class="overallClass">{{ overallText }}</span></span>
      <span>更新时间：{{ updatedAt || '-' }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Server, Brain, Database, HardDrive, RefreshCw, Loader2 } from '@lucide/vue'
import { api } from '../api'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import CardContent from '../components/ui/CardContent.vue'
import Button from '../components/ui/Button.vue'
import Badge from '../components/ui/Badge.vue'

const router = useRouter()
const loading = ref(false)
const refreshingCache = ref(false)
const cacheStatus = ref('加载中...')
const updatedAt = ref('')
const testing = reactive({ backend: false, llm: false, jiandaoyun: false })
const testMessage = reactive({ backend: '', llm: '', jiandaoyun: '' })
const health = reactive({
  backend: { ok: null, message: '' },
  llm: { ok: null, message: '' },
  jiandaoyun: { ok: null, message: '' },
})

const overallText = computed(() => {
  const values = [health.backend.ok, health.llm.ok, health.jiandaoyun.ok]
  if (values.every((v) => v === true)) return '全部正常'
  if (values.some((v) => v === false)) return '存在异常项'
  return '未检查'
})

const overallClass = computed(() => {
  const values = [health.backend.ok, health.llm.ok, health.jiandaoyun.ok]
  if (values.every((v) => v === true)) return 'text-emerald-600 font-medium'
  if (values.some((v) => v === false)) return 'text-destructive font-medium'
  return ''
})

function healthItemClass(ok) {
  if (ok === true) return 'border-emerald-200 bg-emerald-50/30'
  if (ok === false) return 'border-red-200 bg-red-50/30'
  return ''
}

function goTo(path) {
  router.push(path)
}

async function runTest(module) {
  testing[module] = true
  testMessage[module] = '测试中...'
  try {
    if (module === 'backend') {
      const { data } = await api.get('/api/v1/health')
      testMessage[module] = data?.ok ? '测试通过：后台健康' : '测试失败：后台异常'
    } else if (module === 'llm') {
      const { data } = await api.post('/api/v1/admin/llm-config/test', { target: 'agent_a' })
      testMessage[module] = data?.success ? '测试通过：LLM 可调用' : '测试失败：LLM 调用异常'
    } else if (module === 'jiandaoyun') {
      const { data } = await api.post('/api/v1/admin/config/test', {})
      testMessage[module] = data?.success ? `测试通过：${data.message || '连接正常'}` : '测试失败：简道云异常'
    }
    await loadHealth()
  } catch (error) {
    const detail = error?.response?.data?.detail
    testMessage[module] = `测试失败：${typeof detail === 'string' ? detail : (error?.message || '未知错误')}`
  } finally {
    testing[module] = false
  }
}

async function loadHealth() {
  loading.value = true
  try {
    const { data } = await api.get('/api/v1/admin/maintenance/health')
    health.backend = data.checks?.backend || { ok: false, message: '无数据' }
    health.llm = data.checks?.llm || { ok: false, message: '无数据' }
    health.jiandaoyun = data.checks?.jiandaoyun || { ok: false, message: '无数据' }
    updatedAt.value = new Date(data.timestamp).toLocaleString()
  } catch (error) {
    health.backend = { ok: false, message: '维护接口请求失败' }
    health.llm = { ok: false, message: '维护接口请求失败' }
    health.jiandaoyun = { ok: false, message: '维护接口请求失败' }
    updatedAt.value = new Date().toLocaleString()
  } finally {
    loading.value = false
  }
}

async function loadCacheStatus() {
  try {
    const { data } = await api.get('/api/v1/admin/maintenance/health')
    const total = data.customer_index_items_count
    const at = data.customer_index_cache_at
    cacheStatus.value = at ? `${total} 条 (缓存时间: ${new Date(at).toLocaleString()})` : `${total} 条 (缓存未就绪)`
  } catch {
    cacheStatus.value = '获取缓存状态失败'
  }
}

async function refreshCache() {
  refreshingCache.value = true
  cacheStatus.value = '正在刷新客户索引...'
  try {
    const { data } = await api.post('/api/v1/admin/refresh-cache')
    cacheStatus.value = `刷新完成：${data.message}`
  } catch (error) {
    cacheStatus.value = `刷新失败：${error?.response?.data?.detail || error?.message || '未知错误'}`
  } finally {
    refreshingCache.value = false
  }
}

onMounted(() => {
  loadHealth()
  loadCacheStatus()
})
</script>
