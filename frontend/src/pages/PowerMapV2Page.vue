<template>
  <div class="flex flex-col gap-4 min-h-[calc(100vh-170px)] relative">
    <!-- Top toolbar -->
    <div class="flex items-center justify-between gap-3 bg-card border border-border/60 rounded-xl px-4 py-2.5">
      <div class="flex items-center gap-3">
        <h2 class="text-sm font-semibold flex items-center gap-2">
          <MapIcon class="h-4 w-4 text-primary" />
          客户权利地图
        </h2>
        <span v-if="!loadingMap && mapData.nodes" class="text-xs text-muted-foreground">
          {{ mapData.nodes?.length || 0 }} 节点 · {{ mapData.edges?.length || 0 }} 连线
        </span>
      </div>

      <div class="flex items-center gap-2">
        <!-- View mode -->
        <div class="flex items-center bg-muted rounded-lg p-0.5">
          <button
            class="px-2.5 py-1 rounded-md text-xs font-medium transition-all"
            :class="viewMode === 'iframe' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
            @click="viewMode = 'iframe'">原版</button>
          <button
            class="px-2.5 py-1 rounded-md text-xs font-medium transition-all"
            :class="viewMode === 'preview' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
            @click="viewMode = 'preview'">预览(沙箱)</button>
        </div>

        <!-- Version selector -->
        <SelectNative
          v-if="versions.length > 1"
          :model-value="currentVer"
          class="h-9 w-auto text-xs"
          @update:model-value="switchVersion($event)"
        >
          <option v-for="v in versions" :key="v.value" :value="v.value">{{ v.ver_name }}</option>
        </SelectNative>

        <Button variant="ghost" size="sm" class="h-8 text-xs" @click="panelOpen = !panelOpen">
          <MessageSquare class="h-3.5 w-3.5 mr-1" />{{ panelOpen ? '收起' : '维护' }}
        </Button>
      </div>
    </div>

    <!-- Main stage: iframe fills, chat panel floats from right -->
    <div class="flex-1 relative min-h-[500px] bg-card border border-border/60 rounded-xl overflow-hidden">
      <div v-if="!customerStore.currentCustomer" class="absolute inset-0 flex items-center justify-center">
        <div class="text-center space-y-2">
          <User class="h-10 w-10 mx-auto text-muted-foreground/30" />
          <p class="text-sm text-muted-foreground">请先在侧边栏选择客户</p>
        </div>
      </div>
      <div v-else-if="loadingMap" class="absolute inset-0 flex items-center justify-center">
        <div class="text-center space-y-2">
          <Loader2 class="h-8 w-8 mx-auto animate-spin text-primary" />
          <p class="text-sm text-muted-foreground">加载中...</p>
        </div>
      </div>
      <template v-else>
        <!-- iframe mode (原版) -->
        <div v-if="viewMode === 'iframe'" class="absolute inset-0">
          <div v-if="!biIframeUrl" class="absolute inset-0 flex items-center justify-center">
            <div class="text-center space-y-2">
              <Loader2 class="h-8 w-8 mx-auto animate-spin text-primary" />
              <p class="text-sm text-muted-foreground">加载 BI 地址中...</p>
            </div>
          </div>
          <iframe
            v-else
            :key="`bi-${currentVer}-${chatStore.commitRefreshKey}-${biIframeUrl}`"
            :src="biIframeUrl"
            class="absolute inset-0 w-full h-full border-none"
            @load="onIframeLoad"
            @error="onIframeError"
          />
          <div
            v-if="showBiLoginHint"
            class="absolute bottom-4 left-1/2 -translate-x-1/2 bg-card border border-border shadow-lg px-5 py-3 rounded-xl text-center"
          >
            <p class="text-sm mb-2 text-muted-foreground">如果看不到内容，请先在帆软 BI 中登录</p>
            <Button variant="outline" size="sm" @click="openBiLogin">登录帆软 BI</Button>
          </div>
        </div>

        <!-- Preview mode (沙箱 iframe) -->
        <div v-else class="absolute inset-0 bg-muted/20">
          <div v-if="!sandboxIframeUrl" class="absolute inset-0 flex items-center justify-center text-center">
            <div class="space-y-2">
            <ImageIcon class="h-10 w-10 mx-auto text-muted-foreground/30" />
            <p class="text-sm text-muted-foreground">暂无预览，请先在右侧发起聊天</p>
              <p class="text-xs text-muted-foreground/70">AI 完成调整后会刷新沙箱预览</p>
            </div>
          </div>
          <iframe
            v-else
            :key="sandboxIframeKey"
            :src="sandboxIframeUrl"
            class="absolute inset-0 w-full h-full border-none bg-background"
            title="sandbox preview"
          />
        </div>
      </template>

      <!-- Floating chat panel overlay -->
      <Transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0"
        leave-active-class="transition duration-200 ease-in"
        leave-to-class="opacity-0"
      >
        <div v-if="panelOpen" class="absolute inset-0 z-40">
          <!-- Backdrop -->
          <div class="absolute inset-0 bg-black/30" @click="panelOpen = false" />
          <!-- Panel -->
          <aside
            class="absolute right-0 top-0 h-full w-[420px] max-w-full bg-card border-l border-border/60 shadow-2xl flex flex-col z-10"
          >
            <div class="flex items-center justify-between px-4 py-3 border-b border-border/50 shrink-0">
              <h3 class="text-sm font-semibold flex items-center gap-2">
                <MessageSquare class="h-4 w-4 text-primary" />
                权利地图维护
              </h3>
              <Button variant="ghost" size="icon" class="h-7 w-7" @click="panelOpen = false">
                <X class="h-4 w-4" />
              </Button>
            </div>
            <div class="flex-1 min-h-0 overflow-hidden">
              <ChatV2Panel :embedded="true" :version="currentVer" />
            </div>
          </aside>
        </div>
      </Transition>
    </div>

    <!-- Floating reopen tab when collapsed -->
    <button
      v-if="!panelOpen"
      class="fixed right-0 top-1/2 -translate-y-1/2 bg-card border border-border border-r-0 rounded-l-xl px-2 py-3 cursor-pointer flex flex-col items-center gap-1 shadow-md z-30 transition-colors hover:bg-muted"
      @click="panelOpen = true"
      title="打开维护面板"
    >
      <MessageSquare class="h-4 w-4 text-muted-foreground" />
      <span class="text-[10px] [writing-mode:vertical-rl] text-muted-foreground tracking-widest">维护</span>
    </button>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  Map as MapIcon,
  MessageSquare,
  User,
  X,
  Loader2,
  Image as ImageIcon,
} from '@lucide/vue'
import { api } from '../api'
import { useCustomerStore } from '../stores/customer'
import { usePowerMapChatStore } from '../stores/powerMapChat'
import ChatV2Panel from './ChatV2Panel.vue'
import Button from '../components/ui/Button.vue'
import SelectNative from '../components/ui/SelectNative.vue'

const customerStore = useCustomerStore()
const chatStore = usePowerMapChatStore()

const panelOpen = ref(false)
const viewMode = ref('iframe')

const mapData = ref({ nodes: [], edges: [] })
const versions = ref([])
const currentVer = ref('')
const loadingMap = ref(false)

const biIframeUrl = ref('')
const biBaseUrl = ref('')
const showBiLoginHint = ref(false)

const lastScreenshot = computed(() => chatStore.lastScreenshot)
const sandboxIframeUrl = computed(() => {
  const rawUrl = chatStore.sandboxUrl || ''
  if (!rawUrl) return ''
  try {
    const u = new URL(rawUrl, window.location.origin)
    u.searchParams.set('r', String(chatStore.sandboxRefreshKey))
    return `${u.pathname}${u.search}${u.hash}`
  } catch {
    return rawUrl
  }
})
const sandboxIframeKey = computed(() => `${chatStore.sandboxUrl || 'empty'}-${chatStore.sandboxRefreshKey}`)

async function loadBiUrl() {
  if (!customerStore.currentCustomer) return
  try {
    const { data } = await api.get(
      `/api/v1/power-map/${customerStore.currentCustomer.company_id}/bi-com-id`,
    )
    biBaseUrl.value = data.bi_base_url || ''
    const biComId = data.bi_com_id || ''
    if (!biComId) {
      biIframeUrl.value = ''
      return
    }
    const params = new URLSearchParams({ prj_id: String(biComId) })
    if (currentVer.value) params.set('version', currentVer.value)
    biIframeUrl.value = `/api/power_map/sandbox?${params.toString()}`
  } catch (e) {
    console.error('获取 BI URL 失败', e)
    biIframeUrl.value = ''
  }
}

function openBiLogin() {
  const url = biBaseUrl.value || 'https://crm.finereporthelp.com'
  window.open(url, '_blank', 'width=1200,height=800')
}

function onIframeLoad() {
  showBiLoginHint.value = false
}

function onIframeError() {
  showBiLoginHint.value = true
}

async function loadMap() {
  if (!customerStore.currentCustomer) {
    mapData.value = { nodes: [], edges: [] }
    versions.value = []
    return
  }
  loadingMap.value = true
  try {
    const verParam = currentVer.value ? `?version=${currentVer.value}` : ''
    const { data } = await api.get(
      `/api/v1/power-map/${customerStore.currentCustomer.company_id}${verParam}`,
    )
    mapData.value = data.map_data || { nodes: [], edges: [] }
    const vi = mapData.value.version_info || []
    if (vi.length) {
      versions.value = vi
      if (!currentVer.value) {
        const csVer = vi.find(v => (v.ver_name || '').includes('客户成功'))
        const coVer = vi.find(v => (v.ver_name || '').includes('公司'))
        const initialVer = (csVer || coVer || vi[0]).value || ''
        if (initialVer) {
          currentVer.value = initialVer
          return await loadMap()
        }
      }
    }
    if (versions.value.length && !versions.value.find((v) => v.value === currentVer.value)) {
      const csVer = versions.value.find(v => (v.ver_name || '').includes('客户成功'))
      const coVer = versions.value.find(v => (v.ver_name || '').includes('公司'))
      currentVer.value = (csVer || coVer || versions.value[0]).value || ''
    }
    await loadBiUrl()
  } catch (e) {
    console.error('加载权利地图失败', e)
    mapData.value = { nodes: [], edges: [] }
  } finally {
    loadingMap.value = false
  }
}

function switchVersion(verValue) {
  currentVer.value = verValue
  loadMap()
}

watch(
  () => customerStore.currentCustomer?.company_id,
  async () => {
    currentVer.value = ''
    biIframeUrl.value = ''
    await loadMap()
  },
)

watch(lastScreenshot, (shot) => {
  if (shot && viewMode.value === 'iframe') {
    viewMode.value = 'preview'
  }
})

watch(
  () => chatStore.currentSessionId,
  (sessionId) => {
    if (sessionId && viewMode.value === 'iframe') {
      viewMode.value = 'preview'
    }
  },
)

onMounted(() => {
  loadMap()
})
</script>
