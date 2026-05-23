<template>
  <div class="flex flex-col gap-4 min-h-[calc(100vh-190px)] relative">
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
            class="px-2.5 py-1 rounded-md text-xs font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            :class="viewMode === 'preview' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
            :disabled="!pendingChanges"
            @click="viewMode = 'preview'">预览</button>
          <button
            class="px-2.5 py-1 rounded-md text-xs font-medium transition-all"
            :class="viewMode === 'tree' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
            @click="viewMode = 'tree'">树状</button>
        </div>

        <!-- Version selector -->
        <SelectNative v-if="versions.length > 1" :model-value="currentVer" class="h-8 w-auto text-xs" @update:model-value="switchVersion($event)">
          <option v-for="v in versions" :key="v.value" :value="v.value">{{ v.ver_name }}</option>
        </SelectNative>

        <Button variant="outline" size="sm" class="h-8 text-xs" @click="showRelayout = !showRelayout">
          <Wrench class="h-3.5 w-3.5 mr-1" />整理
        </Button>

        <Button variant="ghost" size="sm" class="h-8 text-xs" @click="panelOpen = !panelOpen">
          <MessageSquare class="h-3.5 w-3.5 mr-1" />{{ panelOpen ? '收起' : '维护' }}
        </Button>
      </div>
    </div>

    <!-- Relayout controls -->
    <div v-if="showRelayout" class="bg-muted/30 border border-border/60 rounded-xl p-3 flex items-center gap-3 flex-wrap">
      <span class="text-xs text-muted-foreground">模式：</span>
      <SelectNative v-model="relayoutMode" class="h-8 px-2 text-xs w-auto">
        <option value="new_nodes_only">A 新增整理 — 摆放无坐标的新节点</option>
        <option value="single_dept">B 单部门重排 — 选一个部门紧凑排列</option>
        <option value="full">C 全图重排 — 整张图全部重排（locked 节点不动）</option>
      </SelectNative>
      <span v-if="relayoutMode === 'single_dept'" class="text-xs text-muted-foreground">部门：</span>
      <SelectNative v-if="relayoutMode === 'single_dept'" v-model="relayoutDeptId" class="h-8 px-2 text-xs w-auto">
        <option value="">— 选择部门 —</option>
        <option v-for="d in deptNodes" :key="d.id" :value="d.id">{{ d.name }}</option>
      </SelectNative>
      <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="relayoutRunning || (relayoutMode==='single_dept' && !relayoutDeptId)" @click="doRelayout">
        <Loader2 v-if="relayoutRunning" class="h-3.5 w-3.5 mr-1 animate-spin" />
        {{ relayoutRunning ? '整理中...' : '执行整理' }}
      </Button>
      <span v-if="relayoutMsg" class="text-xs text-muted-foreground">{{ relayoutMsg }}</span>
    </div>

    <!-- Main content area -->
    <div class="flex-1 flex gap-0 min-h-0">
      <!-- Left: Map area -->
      <div class="flex-1 bg-card border border-border/60 rounded-xl overflow-hidden flex flex-col min-w-0" :class="panelOpen ? 'mr-[420px]' : ''">
        <div v-if="!customerStore.currentCustomer" class="flex items-center justify-center h-full">
          <div class="text-center space-y-2">
            <User class="h-10 w-10 mx-auto text-muted-foreground/30" />
            <p class="text-sm text-muted-foreground">请先在侧边栏选择客户</p>
          </div>
        </div>
        <div v-else-if="loadingMap" class="flex items-center justify-center h-full">
          <div class="text-center space-y-2">
            <Loader2 class="h-8 w-8 mx-auto animate-spin text-primary" />
            <p class="text-sm text-muted-foreground">加载中...</p>
          </div>
        </div>
        <div v-else class="flex-1 overflow-auto p-2">

        <!-- iframe mode -->
        <div v-if="viewMode === 'iframe'" class="flex-1 relative min-h-[400px]">
          <div v-if="!biIframeUrl" class="flex items-center justify-center h-full">
            <div class="text-center space-y-2">
              <Loader2 class="h-8 w-8 mx-auto animate-spin text-primary" />
              <p class="text-sm text-muted-foreground">加载 BI 地址中...</p>
            </div>
          </div>
          <iframe v-else :src="biIframeUrl" class="w-full h-full min-h-[600px] border-none rounded-lg"
            @load="onIframeLoad" @error="onIframeError"></iframe>
          <div class="absolute bottom-4 left-1/2 -translate-x-1/2 bg-card border border-border shadow-lg px-5 py-3 rounded-xl text-center" v-if="showBiLoginHint">
            <p class="text-sm mb-2 text-muted-foreground">如果看不到内容，请先在帆软 BI 中登录</p>
            <Button variant="outline" size="sm" @click="openBiLogin">登录帆软 BI</Button>
          </div>
        </div>

        <!-- Preview mode -->
        <div v-else-if="viewMode === 'preview'" class="flex-1 min-h-[500px] relative">
          <div v-if="!selectedProjectId" class="flex items-center justify-center h-full">
            <p class="text-sm text-muted-foreground">请先选择一个项目</p>
          </div>
          <template v-else>
            <div v-if="sandboxLoading" class="absolute inset-0 flex items-center justify-center bg-background/50 z-10">
              <Loader2 class="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
            <iframe
              :key="sandboxIframeKey"
              :src="sandboxUrl"
              class="w-full h-full min-h-[500px] border-0"
              sandbox="allow-scripts allow-same-origin"
              @load="onSandboxLoad"
            />
          </template>
        </div>

        <!-- Tree mode -->
        <template v-else>
          <div v-if="!mapData.nodes?.length" class="flex items-center justify-center h-full">
            <div class="text-center space-y-2">
              <MapIcon class="h-10 w-10 mx-auto text-muted-foreground/30" />
              <p class="text-sm text-muted-foreground">该客户暂无权利地图数据</p>
              <p class="text-xs text-muted-foreground">在右侧对话框中输入指令来创建（如"添加张总为决策者"）</p>
            </div>
          </div>
          <svg
          v-else
          ref="svgRef"
          :viewBox="`0 0 ${GRAPH.w} ${GRAPH.h}`"
          preserveAspectRatio="xMidYMid meet"
          class="w-full h-full min-h-[400px] bg-muted rounded-lg"
        >
          <defs>
            <marker id="pm-arrow" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="#78909c" />
            </marker>
            <filter id="card-shadow">
              <feDropShadow dx="0" dy="2" stdDeviation="2" flood-opacity="0.08" />
            </filter>
          </defs>
          <g :transform="transform">
            <!-- edges -->
            <g class="edges">
              <g v-for="edge in visibleEdges" :key="edge.id">
                <path :d="getEdgePath(edge)" class="fill-none stroke-[#78909c] stroke-[1.5]"
                  marker-end="url(#pm-arrow)" />
                <text v-if="edge.remark"
                  :x="getEdgeMidpoint(edge).x" :y="getEdgeMidpoint(edge).y"
                  class="text-[11px] fill-[#78909c] [text-anchor:middle]">{{ edge.remark }}</text>
              </g>
            </g>
            <!-- cross-branch edges -->
            <g class="cross-edges" v-if="crossEdgesVisible.length">
              <path v-for="ce in crossEdgesVisible" :key="ce.id"
                :d="getEdgePath(ce)"
                fill="none" stroke="#ef5350" stroke-dasharray="5 3" stroke-width="1.3" opacity="0.55" />
            </g>
            <!-- department nodes -->
            <g class="dept-nodes" v-if="deptTreeNodes.length">
              <g v-for="item in deptTreeNodes" :key="item.id"
                :transform="`translate(${item.x}, ${item.y})`">
                <rect
                  :x="-Math.max(item.name.length * 7 + 15, 40)"
                  y="-18"
                  :width="Math.max(item.name.length * 14 + 30, 80)"
                  height="36"
                  rx="6"
                  :fill="item.background || '#fff8e1'"
                  stroke="#1565c0"
                  stroke-width="1.5"
                />
                <text text-anchor="middle" dy="5" font-size="12" font-weight="700"
                  fill="#1565c0">{{ item.name.length > 18 ? item.name.slice(0, 17) + '…' : item.name }}</text>
              </g>
            </g>
            <!-- main nodes -->
            <g class="nodes cursor-pointer">
              <NodeCard v-for="node in visibleMainNodes" :key="node.id"
                :node="node"
                :x="nodeCoords.get(node.id)?.x ?? 0"
                :y="nodeCoords.get(node.id)?.y ?? 0"
                :collapsed="collapsedSet.has(node.id)"
                :child-count="getChildCount(node.id)"
                :descendant-count="getDescendantCount(node.id)"
                @toggle="toggleCollapse"
                @click="handleNodeClick" />
            </g>
            <!-- orphan area -->
            <template v-if="orphanNodes.length">
              <line v-if="showOrphans"
                :x1="PADDING" :y1="orphanAreaY - 24"
                :x2="GRAPH.w - PADDING" :y2="orphanAreaY - 24"
                stroke="#cbd5e1" stroke-dasharray="6 4" />
              <text :x="20" :y="orphanAreaY - 32"
                class="text-xs fill-[#94a3b8] cursor-pointer select-none hover:fill-[#64748b]" @click="showOrphans = !showOrphans">
                游离节点 ({{ orphanNodes.length }}) {{ showOrphans ? '▾' : '▸' }}
              </text>
              <g v-if="showOrphans" class="orphan-nodes">
                <NodeCard v-for="(node, i) in orphanLayout" :key="node.id"
                  :node="node"
                  :x="node._x"
                  :y="node._y"
                  :is-orphan="true"
                  @click="handleNodeClick" />
              </g>
            </template>
          </g>
        </svg>
        </template>
        </div>
      </div>
    </div>

    <!-- Right panel: Chat -->
    <aside
      class="fixed top-0 right-0 h-full z-40 transition-all duration-300 bg-card border-l border-border shadow-xl flex flex-col"
      :class="panelOpen ? 'w-[420px]' : 'w-0 border-l-0 shadow-none overflow-hidden'"
    >
      <div class="flex items-center justify-between px-5 py-4 border-b border-border/50 shrink-0">
        <h3 class="text-sm font-semibold flex items-center gap-2">
          <MessageSquare class="h-4 w-4 text-primary" />
          权利地图维护
        </h3>
        <Button variant="ghost" size="icon" class="h-8 w-8" @click="panelOpen = false">
          <X class="h-4 w-4" />
        </Button>
      </div>

      <div v-if="!customerStore.currentCustomer" class="flex items-center justify-center flex-1">
        <p class="text-sm text-muted-foreground">请先在侧边栏选择客户</p>
      </div>
      <div v-else class="flex flex-col flex-1 min-h-0 p-4">
        <!-- Messages -->
        <div class="flex-1 min-h-[200px] overflow-auto rounded-xl border border-border/50 bg-muted/30 p-3 mb-3 space-y-2.5" ref="chatLog">
          <div v-if="!messages.length" class="flex items-center justify-center h-full">
            <div class="text-center space-y-1">
              <MessageSquare class="h-8 w-8 mx-auto text-muted-foreground/30" />
              <p class="text-xs text-muted-foreground">输入指令管理权利地图</p>
            </div>
          </div>
          <template v-for="(item, idx) in messages" :key="idx">
            <!-- Harness streaming card -->
            <div
              v-if="item.type === 'harness'"
              class="harness-card relative rounded-xl border border-border/60 overflow-hidden"
              :class="{ 'harness-card--active': !item.state.done }"
            >
              <div class="harness-card__bg" aria-hidden="true"></div>

              <!-- Header strip -->
              <div class="harness-header relative flex items-center justify-between px-3.5 py-2 border-b border-border/50">
                <div class="flex items-center gap-2.5">
                  <span class="harness-icon" :class="{ 'harness-icon--pulse': !item.state.done }">
                    <Sparkles class="h-3.5 w-3.5" />
                  </span>
                  <span class="harness-title">HARNESS<span class="opacity-30 mx-1.5">/</span>布局优化</span>
                  <span v-if="!item.state.done" class="harness-dots ml-0.5">
                    <span class="harness-dot"></span>
                    <span class="harness-dot" style="animation-delay:0.18s"></span>
                    <span class="harness-dot" style="animation-delay:0.36s"></span>
                  </span>
                </div>
                <div class="harness-meta flex items-center gap-2">
                  <span class="harness-meta-num">R{{ item.state.currentRound || 0 }}</span>
                  <span class="opacity-30">·</span>
                  <span>{{ harnessOpCount(item.state) }} ops</span>
                </div>
              </div>

              <!-- Body -->
              <div class="harness-body relative max-h-[440px] overflow-y-auto px-3.5 py-3 space-y-3.5">
                <!-- Connecting state -->
                <div v-if="!item.state.rounds.length && !item.state.error" class="flex items-center gap-2 text-[11.5px] font-mono text-muted-foreground/80">
                  <Loader2 class="h-3 w-3 animate-spin" />
                  <span>建立流式连接</span>
                  <span class="harness-ellipsis"></span>
                </div>

                <!-- Rounds -->
                <div
                  v-for="(round, ri) in item.state.rounds"
                  :key="ri"
                  class="harness-round"
                >
                  <div class="flex items-center gap-2 mb-2">
                    <span class="harness-round-badge" :class="{ 'harness-round-badge--active': round.streaming }">
                      R{{ round.round }}
                    </span>
                    <div class="flex-1 h-px bg-gradient-to-r from-primary/40 via-border/60 to-transparent"></div>
                    <span v-if="round.streaming" class="text-[10px] font-mono text-primary/70 tracking-wider">THINKING</span>
                  </div>

                  <div
                    v-if="round.thought"
                    class="harness-thought"
                  >
                    <span class="harness-thought-bar" aria-hidden="true"></span>
                    <span class="harness-thought-text">{{ round.thought }}</span><span v-if="round.streaming" class="harness-caret">▍</span>
                  </div>

                  <div class="harness-toolcalls mt-1.5 space-y-1">
                    <div
                      v-for="(tc, ti) in round.toolCalls"
                      :key="ti"
                      class="harness-toolcall"
                      :style="{ animationDelay: ti * 48 + 'ms' }"
                    >
                      <span class="harness-toolcall-status">
                        <Loader2 v-if="tc.pending" class="h-3 w-3 animate-spin text-amber-500" />
                        <CheckCircle2 v-else-if="tc.ok" class="h-3 w-3 text-emerald-500" />
                        <XCircle v-else class="h-3 w-3 text-rose-500" />
                      </span>
                      <div class="harness-toolcall-body">
                        <code class="harness-toolcall-code">
                          <span class="harness-tool-name">{{ tc.tool }}</span><span class="harness-tool-paren">(</span><span class="harness-tool-args">{{ formatHarnessArgs(tc.args) }}</span><span class="harness-tool-paren">)</span>
                        </code>
                        <div v-if="tc.error" class="harness-toolcall-error">
                          <span class="opacity-60">↳</span> {{ tc.error }}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Done banner -->
                <div
                  v-if="item.state.done && !item.state.error"
                  class="harness-banner harness-banner--done"
                >
                  <CheckCircle2 class="h-3.5 w-3.5 shrink-0" />
                  <div class="flex-1 flex items-baseline gap-2 flex-wrap">
                    <span class="harness-banner__title">完成</span>
                    <span class="harness-banner__detail">{{ item.state.currentRound || item.state.rounds.length }} 轮 · 执行 {{ item.state.executed }} 个调整</span>
                  </div>
                  <span class="harness-banner__time">{{ harnessDurationLabel(item.state) }}</span>
                </div>

                <!-- Error banner -->
                <div
                  v-if="item.state.done && item.state.error"
                  class="harness-banner harness-banner--error"
                >
                  <AlertTriangle class="h-3.5 w-3.5 shrink-0" />
                  <span class="harness-banner__title">{{ item.state.error }}</span>
                  <span class="harness-banner__time">{{ harnessDurationLabel(item.state) }}</span>
                </div>
              </div>
            </div>

            <!-- Regular message -->
            <div
              v-else
              class="rounded-xl px-3 py-2.5 text-sm break-words"
              :class="item.role === 'user' ? 'bg-primary/10 ml-8' : 'bg-card border border-border/50 mr-8'"
            >
              <div class="text-xs font-semibold mb-1 opacity-60">{{ item.role === 'user' ? '我' : '助手' }}</div>
              <div class="whitespace-pre-wrap">{{ item.text }}</div>
              <div v-if="item.changes" class="mt-2 space-y-1.5">
                <div v-if="item.changes.nodes_add?.length" class="rounded-lg p-2 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <strong>+ 新增节点 ({{ item.changes.nodes_add.length }})</strong>
                  <ul class="mt-1 ml-4 list-disc"><li v-for="n in item.changes.nodes_add" :key="n.id">{{ n.label || n.id }}</li></ul>
                </div>
                <div v-if="item.changes.nodes_update?.length" class="rounded-lg p-2 text-xs bg-amber-50 text-amber-700 border border-amber-200">
                  <strong>✎ 更新节点 ({{ item.changes.nodes_update.length }})</strong>
                  <ul class="mt-1 ml-4 list-disc"><li v-for="n in item.changes.nodes_update" :key="n.id">{{ n.label || n.id }}</li></ul>
                </div>
                <div v-if="item.changes.nodes_delete?.length" class="rounded-lg p-2 text-xs bg-red-50 text-red-700 border border-red-200">
                  <strong>✕ 删除节点 ({{ item.changes.nodes_delete.length }})</strong>
                  <ul class="mt-1 ml-4 list-disc"><li v-for="id in item.changes.nodes_delete" :key="id">{{ id }}</li></ul>
                </div>
                <div v-if="item.changes.edges_add?.length" class="rounded-lg p-2 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <strong>+ 新增连线 ({{ item.changes.edges_add.length }})</strong>
                </div>
                <div v-if="item.changes.edges_delete?.length" class="rounded-lg p-2 text-xs bg-red-50 text-red-700 border border-red-200">
                  <strong>✕ 删除连线 ({{ item.changes.edges_delete.length }})</strong>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- Version selector in chat -->
        <div class="mb-2" v-if="versions.length > 1">
          <SelectNative v-model="chatVersion" class="w-full text-xs h-8">
            <option value="">版本：默认</option>
            <option v-for="v in versions" :key="v.value" :value="v.value">{{ v.ver_name }}</option>
          </SelectNative>
        </div>

        <!-- Input -->
        <div class="flex gap-2">
          <Input
            v-model="input"
            class="flex-1 h-9 text-sm"
            placeholder="输入指令，如：添加张总为决策者"
            :disabled="sending"
            @keyup.enter="send(false)"
          />
          <Button variant="outline" size="sm" class="h-9" :disabled="sending || !input.trim()" @click="send(false)">
            <Send v-if="!sending" class="h-4 w-4" />
            <Loader2 v-else class="h-4 w-4 animate-spin" />
          </Button>
          <Button variant="default" size="sm" class="h-9 bg-emerald-600 hover:bg-emerald-700" :disabled="!needsConfirm || sending" @click="send(true)">
            <Check v-if="!sending" class="h-4 w-4 mr-1" />执行
          </Button>
        </div>
      </div>
    </aside>

    <!-- Toggle button when panel is closed -->
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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, watchEffect } from 'vue'
import { select } from 'd3-selection'
import { zoom, zoomIdentity } from 'd3-zoom'
import { linkVertical } from 'd3-shape'
import { hierarchy, tree as d3tree } from 'd3-hierarchy'
import {
  Map as MapIcon,
  MessageSquare,
  User,
  X,
  Check,
  Send,
  Wrench,
  Loader2,
  Sparkles,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from '@lucide/vue'
import { api } from '../api'
import { useCustomerStore } from '../stores/customer'
import NodeCard from '../components/NodeCard.vue'
import Button from '../components/ui/Button.vue'
import Input from '../components/ui/Input.vue'
import SelectNative from '../components/ui/SelectNative.vue'

const customerStore = useCustomerStore()
const mapData = ref({ nodes: [], edges: [] })
const mapVersion = ref(null)
const versions = ref([]) // [{ver_name, value, ...}]
const currentVer = ref('') // selected ver_info value
const chatVersion = ref('') // chat dialog version selector
const loadingMap = ref(false)
const input = ref('')
const messages = ref([])
const sending = ref(false)
const chatLog = ref(null)
const pendingChanges = ref(null)
const needsConfirm = ref(false)
const panelOpen = ref(false) // 右侧对话框折叠状态

// --- Harness streaming state ---
const harnessActive = ref(false)
let activeHarnessES = null
// Session id returned by the harness; reused on subsequent /harness-stream
// requests so the backend can keep accumulating draft changes in memory.
const harnessSessionId = ref('')
// Latest server-pushed graph state (raw graph_state SSE payload). The
// frontend can build a fresh tree from this without re-fetching BI.
const harnessGraphState = ref(null)

function formatHarnessArgValue(value) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string') {
    const v = value.length > 32 ? value.slice(0, 30) + '…' : value
    return `"${v}"`
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return `[${value.length}]`
  try {
    const s = JSON.stringify(value)
    return s.length > 32 ? s.slice(0, 30) + '…' : s
  } catch {
    return String(value)
  }
}

function formatHarnessArgs(args) {
  if (!args || typeof args !== 'object') return ''
  return Object.entries(args)
    .map(([k, v]) => `${k}=${formatHarnessArgValue(v)}`)
    .join(', ')
}

function harnessOpCount(state) {
  let n = 0
  for (const r of (state?.rounds || [])) n += r.toolCalls.length
  return n
}

function harnessDurationLabel(state) {
  if (!state?.startedAt) return ''
  const end = state.finishedAt || Date.now()
  const ms = end - state.startedAt
  if (ms < 1000) return `${ms}ms`
  const s = (ms / 1000).toFixed(1)
  return `${s}s`
}

function autoScrollHarness() {
  scrollChatToBottom()
  nextTick(() => {
    const bodies = document.querySelectorAll('.harness-card .harness-body')
    bodies.forEach((el) => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight
      if (dist < 280) el.scrollTop = el.scrollHeight
    })
  })
}

function startHarnessStream(prjId, companyId) {
  if (activeHarnessES) {
    try { activeHarnessES.close() } catch (e) { /* ignore */ }
    activeHarnessES = null
  }

  const state = reactive({
    rounds: [],
    currentRound: 0,
    executed: 0,
    done: false,
    error: null,
    startedAt: Date.now(),
    finishedAt: null,
  })

  messages.value.push({ role: 'assistant', type: 'harness', state })
  harnessActive.value = true
  scrollChatToBottom()

  const token = localStorage.getItem('zhidang_token') || ''
  const tokenQs = token ? `&token=${encodeURIComponent(token)}` : ''
  const sessionQs = harnessSessionId.value
    ? `&session_id=${encodeURIComponent(harnessSessionId.value)}`
    : ''
  const url = `/api/v1/power-map/${companyId}/harness-stream?prj_id=${encodeURIComponent(prjId)}${tokenQs}${sessionQs}`

  let es
  try {
    es = new EventSource(url)
  } catch (e) {
    state.error = '无法建立流式连接'
    state.done = true
    state.finishedAt = Date.now()
    harnessActive.value = false
    return
  }
  activeHarnessES = es

  const timeoutId = setTimeout(() => {
    if (!state.done) {
      state.error = '执行超时（60s），连接已断开'
      finishStream()
    }
  }, 60000)

  function ensureRound() {
    if (!state.rounds.length) {
      state.rounds.push({ round: 1, thought: '', streaming: true, toolCalls: [] })
      state.currentRound = 1
    }
    return state.rounds[state.rounds.length - 1]
  }

  function finishStream() {
    if (state.done) return
    state.done = true
    state.finishedAt = Date.now()
    state.rounds.forEach((r) => { r.streaming = false })
    harnessActive.value = false
    clearTimeout(timeoutId)
    try { es.close() } catch (e) { /* ignore */ }
    if (activeHarnessES === es) activeHarnessES = null
  }

  es.addEventListener('thinking', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      const cur = ensureRound()
      cur.thought += data.text_chunk || ''
      cur.streaming = true
      autoScrollHarness()
    } catch (e) { console.error('[harness] thinking parse error', e) }
  })

  es.addEventListener('round_start', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      if (data?.session_id) harnessSessionId.value = String(data.session_id)
      state.rounds.forEach((r) => { r.streaming = false })
      const roundNum = Number(data.round) || (state.rounds.length + 1)
      state.rounds.push({ round: roundNum, thought: '', streaming: true, toolCalls: [] })
      state.currentRound = roundNum
      autoScrollHarness()
    } catch (e) { console.error('[harness] round_start parse error', e) }
  })

  es.addEventListener('graph_state', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      if (data?.session_id) harnessSessionId.value = String(data.session_id)
      harnessGraphState.value = data
    } catch (e) { console.error('[harness] graph_state parse error', e) }
  })

  es.addEventListener('tool_call', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      const cur = ensureRound()
      cur.streaming = false
      cur.toolCalls.push({
        tool: data.tool || 'unknown',
        args: data.args || {},
        ok: null,
        error: null,
        pending: true,
      })
      autoScrollHarness()
    } catch (e) { console.error('[harness] tool_call parse error', e) }
  })

  es.addEventListener('tool_result', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      for (let i = state.rounds.length - 1; i >= 0; i--) {
        const r = state.rounds[i]
        for (let j = r.toolCalls.length - 1; j >= 0; j--) {
          const tc = r.toolCalls[j]
          if (tc.pending && (tc.tool === data.tool || !data.tool)) {
            tc.pending = false
            tc.ok = !!data.ok
            tc.error = data.error || null
            if (tc.ok) state.executed += 1
            autoScrollHarness()
            return
          }
        }
      }
    } catch (e) { console.error('[harness] tool_result parse error', e) }
  })

  es.addEventListener('done', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      if (data?.session_id) harnessSessionId.value = String(data.session_id)
      if (data?.executed !== undefined) state.executed = Number(data.executed) || state.executed
      if (data?.rounds !== undefined) state.currentRound = Number(data.rounds) || state.currentRound
      // When the harness reports submitted=true (save_state was called) we
      // discard the cached session id — the next interaction starts fresh.
      if (data?.submitted === true) harnessSessionId.value = ''
    } catch (e) { /* ignore */ }
    finishStream()
    autoScrollHarness()
    loadMap()
  })

  es.onerror = () => {
    if (state.done) return
    if (!state.rounds.length) {
      state.error = '无法连接到服务'
    } else {
      state.error = '连接中断'
    }
    finishStream()
  }
}

const showRelayout = ref(false)
const relayoutMode = ref('new_nodes_only')
const relayoutDeptId = ref('')
const relayoutRunning = ref(false)
const relayoutMsg = ref('')

// 部门列表（从 mapData 中提取，用于 B 模式部门选择器）
const deptNodes = computed(() =>
  (mapData.value.nodes || []).filter(n =>
    (n.type === 'dept' || n.node_type === 'dept' || n.type === 'department' || n.node_type === 'department')
  )
)

// --- 视图模式：iframe（原版） vs tree（树状图）---
const viewMode = ref('iframe')  // 'iframe' | 'tree'
const biIframeUrl = ref('')
const biBaseUrl = ref('')
const showBiLoginHint = ref(false)

async function loadBiUrl() {
  if (!customerStore.currentCustomer) return
  try {
    const { data } = await api.get(`/api/v1/power-map/${customerStore.currentCustomer.company_id}/bi-com-id`)
    biIframeUrl.value = data.bi_iframe_url
    biBaseUrl.value = data.bi_base_url
    const prjId = data.prj_id || data.bi_com_id || data.com_id || ''
    if (prjId) {
      selectedProjectId.value = String(prjId)
    } else if (data.bi_iframe_url) {
      try {
        const u = new URL(data.bi_iframe_url)
        const fromUrl = u.searchParams.get('prj_id') || u.searchParams.get('prj') || u.searchParams.get('com_id') || ''
        if (fromUrl) selectedProjectId.value = fromUrl
      } catch (_) { /* ignore parse error */ }
    }
  } catch (e) {
    console.error('获取 BI URL 失败', e)
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

// --- SVG constants ---
const PADDING = 60
const NODE_W = 168
const NODE_H = 68
const ORPHAN_AREA_H = 100
const ORPHAN_TITLE_H = 28
const ORPHAN_NODE_W = 168
const ORPHAN_NODE_H = 56
const ORPHAN_GAP = 12

// 后端 preview 端点返回的完整数据
const previewMapData = ref(null)

// --- Sandbox iframe preview state ---
const selectedProjectId = ref('')
const sandboxIframeKey = ref(0)
const sandboxLoading = ref(false)

const sandboxUrl = computed(() => {
  if (!selectedProjectId.value) return 'about:blank'
  const base = import.meta.env?.VITE_API_BASE || ''
  const params = new URLSearchParams()
  params.set('prj_id', selectedProjectId.value)
  if (harnessSessionId.value) {
    params.set('session_id', harnessSessionId.value)
  }
  return `${base}/api/power_map/sandbox?${params}`
})

function onSandboxLoad() {
  sandboxLoading.value = false
}

function refreshSandbox() {
  sandboxLoading.value = true
  sandboxIframeKey.value++
}

watch(viewMode, (mode) => {
  if (mode === 'preview') {
    sandboxLoading.value = true
    sandboxIframeKey.value++
  }
})

// --- Graph state ---
const svgRef = ref(null)
const transform = ref(zoomIdentity.toString())
const showOrphans = ref(true)
const collapsedSet = reactive(new Set())

// --- 0. 数据归一化（兼容后端不同类型表示） ---
const TYPE_ALIAS = {
  dept: 'department',
  department: 'department',
  user: 'person',
  person: 'person',
}

const normalizedNodes = computed(() =>
  (mapData.value.nodes || []).map(n => ({
    ...n,
    id: String(n.id),
    type: TYPE_ALIAS[n.type] || n.type || 'person',
    name: n.name || n.position || `#${n.id}`,
    x: Number(n.x),
    y: Number(n.y),
  }))
)
const normalizedEdges = computed(() =>
  (mapData.value.edges || []).map(e => ({
    ...e,
    source_id: String(e.source_id),
    target_id: String(e.target_id),
  }))
)

// 调试：打印匹配情况
watchEffect(() => {
  const nodeIds = new Set(normalizedNodes.value.map(n => n.id))
  const edgeRefs = new Set()
  normalizedEdges.value.forEach(e => { edgeRefs.add(e.source_id); edgeRefs.add(e.target_id) })
  const missing = [...edgeRefs].filter(id => !nodeIds.has(id))
  console.log('[Graph] 节点数:', normalizedNodes.value.length,
    '边数:', normalizedEdges.value.length,
    '边引用了但找不到的node id:', missing)
})

// --- Node processing ---
const rawNodes = computed(() => normalizedNodes.value)
const rawEdges = computed(() => normalizedEdges.value)

// --- d3.tree() 树状布局 ---
const treeLayout = computed(() => {
  const nodes = rawNodes.value
  const edges = rawEdges.value
  if (!nodes.length) return null

  const nodeMap = new Map()
  nodes.forEach(n => nodeMap.set(String(n.id), n))

  const parentMap = new Map()

  // Step 1: person → person via pid (reports_to chain).
  nodes.forEach(n => {
    if (n.type !== 'person' || !n.pid) return
    const pid = String(n.pid)
    if (nodeMap.has(pid)) parentMap.set(String(n.id), pid)
  })

  // ── DIAG: dump pid-based parent relationships ──
  const pidChildren = []
  nodes.forEach(n => {
    if (n.type !== 'person' || !n.pid) return
    const pid = String(n.pid)
    const parent = nodeMap.get(pid)
    pidChildren.push({ child: n.name, childId: String(n.id).slice(-8), pid: pid.slice(-8), parentName: parent?.name || 'MISSING' })
  })
  console.log('[treeLayout] pidChildren:', JSON.stringify(pidChildren))
  console.log('[treeLayout] parentMap size:', parentMap.size)
  parentMap.forEach((pid, cid) => {
    const c = nodeMap.get(cid)
    const p = nodeMap.get(pid)
    console.log('[treeLayout]   ', c?.name, '→', p?.name || pid.slice(-8))
  })

  // Step 2: person → department (only for persons without a manager).
  // Persons with a pid are already attached above their manager — they
  // shouldn't double-attach to the department or we'd create a cycle.
  nodes.forEach(n => {
    if (n.type !== 'person') return
    if (n.pid) return
    if (!n.node_parent_dept) return
    const pid = String(n.node_parent_dept)
    if (nodeMap.has(pid) && !parentMap.has(String(n.id))) {
      parentMap.set(String(n.id), pid)
    }
  })

  edges.forEach(e => {
    const src = nodeMap.get(String(e.source_id))
    const tgt = nodeMap.get(String(e.target_id))
    if (!src || !tgt) return
    if (src.type === 'department' && tgt.type === 'person') {
      if (!parentMap.has(String(tgt.id))) parentMap.set(String(tgt.id), String(src.id))
    }
    if (src.type === 'department' && tgt.type === 'department') {
      const sid = String(e.source_id), tid = String(e.target_id)
      if (sid !== tid && !parentMap.has(tid)) parentMap.set(tid, sid)
    }
  })

  const deptIds = new Set(nodes.filter(n => n.type === 'department').map(n => String(n.id)))
  const roots = []
  deptIds.forEach(id => {
    if (!parentMap.has(id)) roots.push(id)
  })
  if (!roots.length && deptIds.size) roots.push(deptIds.values().next().value)

  const childMap = new Map()
  const crossEdges = []

  parentMap.forEach((pid, cid) => {
    if (!childMap.has(pid)) childMap.set(pid, [])
    childMap.get(pid).push(cid)
  })

  const visited = new Map()
  const bfs = (rootIds) => {
    const queue = rootIds.map(id => ({ id, d: 0 }))
    queue.forEach(({ id, d }) => visited.set(id, { depth: d, parent: null }))
    while (queue.length) {
      const { id, d } = queue.shift()
      const children = childMap.get(id) || []
      children.forEach(cid => {
        const newDepth = d + 1
        if (!visited.has(cid)) {
          visited.set(cid, { depth: newDepth, parent: id })
          queue.push({ id: cid, d: newDepth })
        } else if (newDepth > visited.get(cid).depth) {
          visited.set(cid, { depth: newDepth, parent: id })
        } else {
          crossEdges.push({ source: id, target: cid })
        }
      })
    }
    return visited
  }

  bfs(roots)

  const buildHierarchy = (nodeId) => {
    const n = nodeMap.get(nodeId)
    if (!n) return null
    const children = (childMap.get(nodeId) || [])
      .filter(cid => visited.get(cid)?.parent === nodeId)
      .map(cid => buildHierarchy(cid))
      .filter(Boolean)
    return {
      id: nodeId,
      name: n.name || n.id,
      type: n.type,
      position: n.position,
      background: n.node_background,
      borderColor: n.node_border_color,
      highlight: n.if_highLight === '2' || n.tagA === 'A',
      children: children.length ? children : undefined,
      _raw: n,
    }
  }

  const trees = roots.map(r => buildHierarchy(r)).filter(Boolean)

  if (!trees.length) {
    const personNodes = nodes.filter(n => n.type === 'person').map(n => ({
      id: String(n.id), name: n.name, type: 'person',
      position: n.position, background: n.node_background,
      borderColor: n.node_border_color,
      highlight: n.if_highLight === '2' || n.tagA === 'A',
      children: undefined, _raw: n,
    }))
    return { trees: [{ id: '__root__', name: '', type: 'root', children: personNodes }], crossEdges: [], nodeMap, visited, parentMap }
  }

  return { trees, crossEdges, nodeMap, visited, parentMap }
})

// --- d3 tree 坐标 ---
const NODE_GAP_X = 200  // 卡片宽168 + 32px间隙
const LEVEL_GAP_Y = 70

const treeCoords = computed(() => {
  const tl = treeLayout.value
  if (!tl) return { positions: new Map(), links: [], crossLinks: [], viewW: 960, viewH: 640 }

  const positions = new Map()
  const allLinks = []
  const allCrossLinks = []

  const makeEndpoint = (id, cx, cy, data) => {
    const dims = nodeDims(data)
    return {
      id: String(id),
      cx, cy,
      x: cx, y: cy,
      w: dims.w,
      h: dims.h,
      type: data?.type,
    }
  }

  tl.trees.forEach((rootData) => {
    const root = hierarchy(rootData)
    const layout = d3tree().nodeSize([NODE_GAP_X, LEVEL_GAP_Y])
      .separation((a, b) => (a.parent === b.parent ? 1.2 : 1.8))
    layout(root)

    root.each(d => {
      positions.set(d.data.id, { x: d.x, y: d.y, type: d.data.type, ...d.data })
    })

    root.links().forEach(l => {
      allLinks.push({
        source: makeEndpoint(l.source.data.id, l.source.x, l.source.y, l.source.data),
        target: makeEndpoint(l.target.data.id, l.target.x, l.target.y, l.target.data),
        cross: false,
      })
    })
  })

  tl.crossEdges.forEach((e, i) => {
    const srcPos = positions.get(e.source)
    const tgtPos = positions.get(e.target)
    if (srcPos && tgtPos) {
      allCrossLinks.push({
        id: `cross-${i}`,
        source: makeEndpoint(e.source, srcPos.x, srcPos.y, srcPos),
        target: makeEndpoint(e.target, tgtPos.x, tgtPos.y, tgtPos),
        cross: true,
      })
    }
  })

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  positions.forEach(p => {
    minX = Math.min(minX, p.x - 80)
    maxX = Math.max(maxX, p.x + 80)
    minY = Math.min(minY, p.y - 20)
    maxY = Math.max(maxY, p.y + 40)
  })
  const viewW = Math.max(maxX - minX + 160, 960)
  const viewH = Math.max(maxY - minY + 120, 640)

  return {
    positions,
    links: allLinks,
    crossLinks: allCrossLinks,
    viewW,
    viewH,
    minX,
    minY,
    maxX,
    maxY,
  }
})

// --- Local layout helpers (Phase B) ---
// These operate on whatever node list is passed in (cloned d3 hierarchies),
// returning fresh coordinates without disturbing the reactive `treeCoords`.
// They are utilities for callers that need scoped recomputation outside the
// global reactivity (e.g. when LLM-driven structure events arrive).

function relayoutSiblings(parentId, nodeList, edgeList) {
  // Lay out direct children of `parentId` and return a Map(id → {x, y, w, h}).
  // Container width/height is sized to wrap children with padding.
  if (!parentId) return new Map()
  const direct = nodeList.filter(n => String(n.parent_id || n.node_parent_dept || '') === String(parentId))
  if (!direct.length) return new Map()
  const out = new Map()
  let cursorX = 0
  const PAD_X = 16
  direct.forEach(n => {
    const w = n.type === 'department' ? 220 : NODE_W
    const h = n.type === 'department' ? 100 : NODE_H
    out.set(String(n.id), { x: cursorX, y: 0, w, h })
    cursorX += w + PAD_X
  })
  // Bounding box of the rearranged children.
  let maxX = 0, maxY = 0
  out.forEach(p => {
    maxX = Math.max(maxX, p.x + p.w)
    maxY = Math.max(maxY, p.y + p.h)
  })
  out.set(`__container_${parentId}`, { x: 0, y: 0, w: maxX + 40, h: maxY + 60 })
  return out
}

function layoutSubtree(rootId, nodeList, edgeList) {
  // Build a hierarchy rooted at `rootId` (children resolved via parent_id /
  // node_parent_dept and pid → reports_to) and run d3.tree on it. Returns
  // Map(id → {x, y}).
  const out = new Map()
  if (!rootId) return out
  const byId = new Map()
  nodeList.forEach(n => byId.set(String(n.id), n))
  if (!byId.has(String(rootId))) return out

  const parentOf = new Map()
  nodeList.forEach(n => {
    const pid = String(n.parent_id || n.node_parent_dept || '')
    if (pid && byId.has(pid)) parentOf.set(String(n.id), pid)
  })
  nodeList.forEach(n => {
    if (n.type === 'person' && n.pid) {
      const reportPid = String(n.pid)
      if (byId.has(reportPid)) parentOf.set(String(n.id), reportPid)
    }
  })

  const children = new Map()
  parentOf.forEach((p, c) => {
    if (!children.has(p)) children.set(p, [])
    children.get(p).push(c)
  })

  const buildTree = (id, depth = 0) => {
    const raw = byId.get(id)
    if (!raw) return null
    const kids = (children.get(id) || []).map(k => buildTree(k, depth + 1)).filter(Boolean)
    return { id, _raw: raw, children: kids.length ? kids : undefined }
  }

  const rootData = buildTree(String(rootId))
  if (!rootData) return out
  const root = hierarchy(rootData)
  const layout = d3tree().nodeSize([NODE_GAP_X, LEVEL_GAP_Y])
    .separation((a, b) => (a.parent === b.parent ? 1.2 : 1.8))
  layout(root)
  root.each(d => out.set(d.data.id, { x: d.x, y: d.y }))
  return out
}

function resolveCollisions(scopeId, positions) {
  // positions: Map(id → {x, y, w, h}). Push overlapping boxes apart along
  // the minimum separation vector. Up to 3 passes per call.
  if (!positions || positions.size < 2) return positions
  const ids = [...positions.keys()].filter(id => !id.startsWith('__container_'))
  for (let pass = 0; pass < 3; pass++) {
    let moved = false
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = positions.get(ids[i])
        const b = positions.get(ids[j])
        if (!a || !b) continue
        const overlapX = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)
        const overlapY = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)
        if (overlapX > 0 && overlapY > 0) {
          if (overlapX <= overlapY) {
            const push = overlapX / 2 + 1
            a.x -= push
            b.x += push
          } else {
            const push = overlapY / 2 + 1
            a.y -= push
            b.y += push
          }
          moved = true
        }
      }
    }
    if (!moved) break
  }
  return positions
}

// 树布局中所有人员节点（非部门）
const visibleMainNodes = computed(() => {
  const tl = treeLayout.value
  if (!tl) return []
  const hidden = new Set()
  for (const id of collapsedSet) {
    for (const d of getDescendants(id)) hidden.add(d)
  }
  return rawNodes.value.filter(n => {
    if (n.type !== 'person') return false
    if (hidden.has(n.id)) return false
    return true
  })
})

const nodeCoords = computed(() => {
  const m = new Map()
  const tc = treeCoords.value
  if (!tc) return m
  tc.positions.forEach((p, id) => {
    if (p.type === 'person') {
      m.set(id, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 })
    }
  })
  return m
})

// 部门节点：树中的部门作为独立卡片展示
const deptTreeNodes = computed(() => {
  const tc = treeCoords.value
  if (!tc) return []
  const result = []
  tc.positions.forEach((p, id) => {
    if (p.type === 'department') {
      result.push({ id, name: p.name, x: p.x, y: p.y, background: p.background })
    }
  })
  return result
})

const orphanNodes = computed(() => {
  const tl = treeLayout.value
  if (!tl) return rawNodes.value.filter(n => n.type === 'person')
  const inTree = new Set()
  tl.visited?.forEach((_, id) => inTree.add(id))
  treeCoords.value?.positions.forEach((_, id) => inTree.add(id))
  return rawNodes.value.filter(n => n.type === 'person' && !inTree.has(String(n.id)))
})

const visibleEdges = computed(() => {
  const tc = treeCoords.value
  if (!tc) return []
  const hidden = new Set()
  for (const id of collapsedSet) {
    for (const d of getDescendants(id)) hidden.add(d)
  }
  return tc.links
    .filter(l => !hidden.has(l.source.id) && !hidden.has(l.target.id))
    .map((l, i) => ({ ...l, id: `edge-${i}` }))
})

const crossEdgesVisible = computed(() => {
  const tc = treeCoords.value
  if (!tc) return []
  return tc.crossLinks
})

// --- Descendant tracking (BFS) ---
function getDescendants(rootId) {
  const result = new Set()
  const queue = [rootId]
  while (queue.length) {
    const cur = queue.shift()
    rawEdges.value.filter(e => e.source_id === cur).forEach(e => {
      if (!result.has(e.target_id)) {
        result.add(e.target_id)
        queue.push(e.target_id)
      }
    })
  }
  return result
}

function getChildCount(id) {
  return rawEdges.value.filter(e => e.source_id === id).length
}

function getDescendantCount(id) {
  return getDescendants(id).size
}

// --- 动态 viewBox ---
const GRAPH = computed(() => {
  const tc = treeCoords.value
  if (!tc) return { w: 960, h: 640 }
  const orphanH = orphanNodes.value.length ? ORPHAN_AREA_H + 60 : 0
  return { w: tc.viewW, h: tc.viewH + orphanH }
})

// --- Edge geometry ---
// Kept as fallback for any legacy code path.
const edgeGen = linkVertical()
  .x(d => d.x)
  .y(d => d.y)

const PORT_SPACING = 10           // px between fan-out ports on the same side
const CTRL_DIST_MIN = 24          // min control-point distance (smaller = tighter bend)
const CTRL_DIST_MAX = 70          // cap so long edges don't curl
const STRAIGHT_THRESHOLD = 80     // edges shorter than this snap to a straight line when collinear

function nodeDims(data) {
  if (data?.type === 'department') {
    const name = data?.name || ''
    return { w: Math.max(name.length * 14 + 30, 80), h: 36 }
  }
  return { w: NODE_W, h: NODE_H }
}

function smartPorts(source, target) {
  const dx = (target.cx ?? target.x) - (source.cx ?? source.x)
  const dy = (target.cy ?? target.y) - (source.cy ?? source.y)
  if (Math.abs(dx) > Math.abs(dy)) {
    return {
      sourcePort: dx > 0 ? 'right' : 'left',
      targetPort: dx > 0 ? 'left' : 'right',
    }
  }
  return {
    sourcePort: dy > 0 ? 'bottom' : 'top',
    targetPort: dy > 0 ? 'top' : 'bottom',
  }
}

function getNodePort(ep, side, offset = 0) {
  const cx = ep.cx ?? ep.x
  const cy = ep.cy ?? ep.y
  const hw = (ep.w ?? NODE_W) / 2
  const hh = (ep.h ?? NODE_H) / 2
  switch (side) {
    case 'top':    return { x: cx + offset, y: cy - hh }
    case 'bottom': return { x: cx + offset, y: cy + hh }
    case 'left':   return { x: cx - hw, y: cy + offset }
    case 'right':  return { x: cx + hw, y: cy + offset }
  }
  return { x: cx, y: cy }
}

function offsetPoint(pt, side, dist) {
  switch (side) {
    case 'top':    return { x: pt.x, y: pt.y - dist }
    case 'bottom': return { x: pt.x, y: pt.y + dist }
    case 'left':   return { x: pt.x - dist, y: pt.y }
    case 'right':  return { x: pt.x + dist, y: pt.y }
  }
  return pt
}

function smoothPath(sP, tP, sSide, tSide) {
  const dx = tP.x - sP.x
  const dy = tP.y - sP.y
  const dist = Math.hypot(dx, dy) || 1
  const horiz = (sSide === 'left' || sSide === 'right')
  const collinear = horiz ? Math.abs(dy) < 4 : Math.abs(dx) < 4
  if (dist < STRAIGHT_THRESHOLD && collinear) {
    return `M ${sP.x} ${sP.y} L ${tP.x} ${tP.y}`
  }
  const ctrlDist = Math.min(Math.max(dist * 0.45, CTRL_DIST_MIN), CTRL_DIST_MAX)
  const c1 = offsetPoint(sP, sSide, ctrlDist)
  const c2 = offsetPoint(tP, tSide, ctrlDist)
  return `M ${sP.x} ${sP.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${tP.x} ${tP.y}`
}

// Pre-compute port side + fan-out offset for every visible edge so
// multiple edges sharing a side don't overlap.
const edgePortInfo = computed(() => {
  const result = new Map()
  const groups = new Map()
  const pushGroup = (key, item) => {
    let arr = groups.get(key)
    if (!arr) { arr = []; groups.set(key, arr) }
    arr.push(item)
  }
  const all = [
    ...visibleEdges.value,
    ...crossEdgesVisible.value,
  ]
  for (const edge of all) {
    if (!edge?.source || !edge?.target) continue
    const { sourcePort, targetPort } = smartPorts(edge.source, edge.target)
    result.set(edge.id, {
      sourceSide: sourcePort,
      targetSide: targetPort,
      sourceOffset: 0,
      targetOffset: 0,
    })
    pushGroup(`${edge.source.id}:${sourcePort}`, { edgeId: edge.id, isSource: true, other: edge.target, side: sourcePort })
    pushGroup(`${edge.target.id}:${targetPort}`, { edgeId: edge.id, isSource: false, other: edge.source, side: targetPort })
  }
  groups.forEach(arr => {
    if (arr.length <= 1) return
    const horizontalSide = arr[0].side === 'top' || arr[0].side === 'bottom'
    arr.sort((a, b) => horizontalSide
      ? (a.other.cx ?? a.other.x) - (b.other.cx ?? b.other.x)
      : (a.other.cy ?? a.other.y) - (b.other.cy ?? b.other.y))
    const total = (arr.length - 1) * PORT_SPACING
    arr.forEach((item, i) => {
      const off = -total / 2 + i * PORT_SPACING
      const info = result.get(item.edgeId)
      if (!info) return
      if (item.isSource) info.sourceOffset = off
      else info.targetOffset = off
    })
  })
  return result
})

function getEdgePath(edge) {
  if (!edge?.source || !edge?.target) return ''
  const info = edgePortInfo.value.get(edge.id) || {
    sourceSide: 'bottom', targetSide: 'top', sourceOffset: 0, targetOffset: 0,
  }
  const sP = getNodePort(edge.source, info.sourceSide, info.sourceOffset)
  const tP = getNodePort(edge.target, info.targetSide, info.targetOffset)
  return smoothPath(sP, tP, info.sourceSide, info.targetSide)
}

function getEdgeMidpoint(edge) {
  if (!edge?.source || !edge?.target) return { x: 0, y: 0 }
  const info = edgePortInfo.value.get(edge.id)
  if (info) {
    const sP = getNodePort(edge.source, info.sourceSide, info.sourceOffset)
    const tP = getNodePort(edge.target, info.targetSide, info.targetOffset)
    return { x: (sP.x + tP.x) / 2, y: (sP.y + tP.y) / 2 }
  }
  return {
    x: ((edge.source.cx ?? edge.source.x) + (edge.target.cx ?? edge.target.x)) / 2,
    y: ((edge.source.cy ?? edge.source.y) + (edge.target.cy ?? edge.target.y)) / 2,
  }
}

// --- Orphan layout ---
const orphanAreaY = computed(() => {
  if (!orphanNodes.value.length) return GRAPH.value.h
  const tc = treeCoords.value
  if (!tc) return GRAPH.value.h - ORPHAN_AREA_H
  return Math.max(tc.maxY || 0, 0) + 40
})

const orphanLayout = computed(() => {
  const nodes = orphanNodes.value
  if (!nodes.length) return []
  const cols = Math.max(1, Math.floor((GRAPH.value.w - PADDING * 2 + ORPHAN_GAP) / (ORPHAN_NODE_W + ORPHAN_GAP)))
  return nodes.map((node, i) => ({
    ...node,
    _x: PADDING + (i % cols) * (ORPHAN_NODE_W + ORPHAN_GAP),
    _y: orphanAreaY.value + Math.floor(i / cols) * (ORPHAN_NODE_H + ORPHAN_GAP),
  }))
})

// --- Interactions ---
function toggleCollapse(id) {
  if (collapsedSet.has(id)) collapsedSet.delete(id)
  else collapsedSet.add(id)
}

function handleNodeClick(node) {
  console.log('Node clicked:', node)
}

// --- Zoom ---
function setupZoom() {
  if (!svgRef.value) return
  const svg = select(svgRef.value)
  const z = zoom()
    .scaleExtent([0.2, 8])
    .on('zoom', (event) => {
      transform.value = event.transform.toString()
    })
  svg.call(z)
}

// --- Chat functions (unchanged) ---
function scrollChatToBottom() {
  nextTick(() => {
    const el = chatLog.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function loadMap() {
  if (!customerStore.currentCustomer) {
    mapData.value = { nodes: [], edges: [] }
    mapVersion.value = null
    versions.value = []
    return
  }
  loadingMap.value = true
  try {
    const verParam = currentVer.value ? `?version=${currentVer.value}` : ''
    const { data } = await api.get(`/api/v1/power-map/${customerStore.currentCustomer.company_id}${verParam}`)
    mapData.value = data.map_data || { nodes: [], edges: [] }
    // 保存版本列表（仅在首次加载或明确有 version_info 时更新）
    const vi = mapData.value.version_info || []
    if (vi.length) {
      versions.value = vi
      if (!currentVer.value) {
        currentVer.value = vi[0].value || ''
      }
    }
    // 如果当前版本不在列表中，重置
    if (versions.value.length && !versions.value.find(v => v.value === currentVer.value)) {
      currentVer.value = versions.value[0].value || ''
    }
    const cur = versions.value.find(v => v.value === currentVer.value)
    mapVersion.value = cur?.ver_name || null
    collapsedSet.clear()
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

async function doRelayout() {
  if (!customerStore.currentCustomer) return
  relayoutRunning.value = true
  relayoutMsg.value = ''
  try {
    const body = { mode: relayoutMode.value, version: chatVersion.value || currentVer.value }
    if (relayoutMode.value === 'single_dept') {
      body.dept_id = relayoutDeptId.value
    }
    const { data } = await api.post(
      `/api/v1/power-map/${customerStore.currentCustomer.company_id}/relayout`,
      body
    )
    relayoutMsg.value = data.message || '整理完成'
    showRelayout.value = false
    // 重新加载地图
    await loadMap()
  } catch (e) {
    relayoutMsg.value = '整理失败: ' + (e.response?.data?.detail || e.message)
  } finally {
    relayoutRunning.value = false
  }
}

async function send(confirm) {
  if (sending.value) return
  if (!customerStore.currentCustomer) return
  if (!confirm && !input.value.trim()) return

  const text = confirm ? '确认执行' : input.value.trim()
  sending.value = true

  try {
    if (confirm && pendingChanges.value) {
      messages.value.push({ role: 'user', text })
      const companyId = customerStore.currentCustomer.company_id
      const { data } = await api.post(
        `/api/v1/power-map/${companyId}/confirm`,
        { proposed_changes: pendingChanges.value, version: chatVersion.value || undefined }
      )
      messages.value.push({ role: 'assistant', text: data.message || '修改已执行' })
      pendingChanges.value = null
      needsConfirm.value = false
      previewMapData.value = null

      const harness = data.harness_report
      const harnessPrjId = harness?.prj_id
      if (harnessPrjId && !harness?.skipped) {
        startHarnessStream(harnessPrjId, companyId)
      } else {
        await loadMap()
      }
    } else {
      messages.value.push({ role: 'user', text })
      const companyId = customerStore.currentCustomer.company_id
      const { data } = await api.post(`/api/v1/power-map/${companyId}/chat`, {
        message: text,
        confirm: false,
        version: chatVersion.value || undefined,
      })
      const reply = data.reply || '收到'
      const hasChanges = data.needs_confirmation && data.changes
      messages.value.push({
        role: 'assistant',
        text: reply,
        changes: data.changes || null,
      })
      if (hasChanges) {
        pendingChanges.value = data.changes
        needsConfirm.value = true
        // 调用预览端点获取带布局坐标的完整数据
        try {
          const previewResp = await api.post(
            `/api/v1/power-map/${customerStore.currentCustomer.company_id}/preview`,
            { proposed_changes: data.changes, version: chatVersion.value || undefined }
          )
          previewMapData.value = previewResp.data
        } catch (e) {
          console.warn('Preview fetch failed, falling back to merge:', e)
          previewMapData.value = null
        }
      } else {
        pendingChanges.value = null
        needsConfirm.value = false
      }
    }
    if (!confirm) input.value = ''
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '请求失败'
    messages.value.push({ role: 'assistant', text: `错误：${detail}` })
  } finally {
    sending.value = false
    scrollChatToBottom()
  }
}

watch(() => customerStore.currentCustomer, () => {
  if (activeHarnessES) {
    try { activeHarnessES.close() } catch (e) { /* ignore */ }
    activeHarnessES = null
    harnessActive.value = false
  }
  messages.value = []
  input.value = ''
  pendingChanges.value = null
  previewMapData.value = null
  needsConfirm.value = false
  currentVer.value = ''
  selectedProjectId.value = ''
  loadMap()
})

onMounted(() => {
  loadMap()
})

onBeforeUnmount(() => {
  if (activeHarnessES) {
    try { activeHarnessES.close() } catch (e) { /* ignore */ }
    activeHarnessES = null
  }
})

// SVG 是条件渲染的（v-else），用 watchEffect 在 SVG 出现后初始化 zoom
let zoomSetup = false
watchEffect(() => {
  if (svgRef.value && !zoomSetup) {
    nextTick(() => { setupZoom(); zoomSetup = true })
  }
  // 当 SVG 消失（换客户时）重置标记
  if (!svgRef.value) zoomSetup = false
})
</script>

<style scoped>
/* ============================================
   Harness streaming card — "neural theatre"
   ============================================ */
.harness-card {
  margin-right: 0.25rem;
  background: linear-gradient(180deg, var(--color-card) 0%, color-mix(in oklab, var(--color-card) 92%, var(--color-primary)) 100%);
  box-shadow:
    0 1px 0 color-mix(in oklab, var(--color-foreground) 4%, transparent) inset,
    0 4px 14px -8px color-mix(in oklab, var(--color-primary) 30%, transparent);
  animation: harness-card-in 0.5s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes harness-card-in {
  from { opacity: 0; transform: translateY(6px) scale(0.99); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* Subtle moving gradient backdrop while active */
.harness-card__bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(120% 60% at 100% 0%, color-mix(in oklab, var(--color-primary) 9%, transparent) 0%, transparent 55%),
    radial-gradient(80%  60% at 0%   100%, color-mix(in oklab, var(--color-primary) 6%, transparent) 0%, transparent 60%);
}
.harness-card--active .harness-card__bg {
  animation: harness-aurora 6.5s ease-in-out infinite alternate;
}
@keyframes harness-aurora {
  0%   { background-position: 0% 0%, 100% 100%; opacity: 0.85; }
  100% { background-position: 100% 30%, 0% 70%; opacity: 1; }
}

/* Header */
.harness-header {
  background: color-mix(in oklab, var(--color-card) 78%, transparent);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.harness-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: color-mix(in oklab, var(--color-primary) 14%, transparent);
  color: var(--color-primary);
  border: 1px solid color-mix(in oklab, var(--color-primary) 22%, transparent);
}
.harness-icon--pulse {
  animation: harness-icon-glow 2.2s ease-in-out infinite;
}
@keyframes harness-icon-glow {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in oklab, var(--color-primary) 40%, transparent); }
  50%      { box-shadow: 0 0 0 4px color-mix(in oklab, var(--color-primary) 0%, transparent); }
}

.harness-title {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', 'SF Mono', ui-monospace, 'Cascadia Mono', Menlo, monospace;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--color-foreground);
}

.harness-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.harness-dot {
  width: 4px;
  height: 4px;
  border-radius: 9999px;
  background: #10b981;
  animation: harness-dot-pulse 1.3s ease-in-out infinite;
}
@keyframes harness-dot-pulse {
  0%, 60%, 100% { opacity: 0.25; transform: translateY(0) scale(0.85); }
  30%           { opacity: 1;    transform: translateY(-2px) scale(1); }
}

.harness-meta {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 10px;
  color: var(--color-muted-foreground);
  letter-spacing: 0.04em;
}
.harness-meta-num {
  color: var(--color-foreground);
  opacity: 0.8;
}

/* Body */
.harness-body {
  position: relative;
  z-index: 1;
}
.harness-body::-webkit-scrollbar { width: 6px; }
.harness-body::-webkit-scrollbar-track { background: transparent; }
.harness-body::-webkit-scrollbar-thumb {
  background: color-mix(in oklab, var(--color-border) 80%, transparent);
  border-radius: 3px;
}
.harness-body::-webkit-scrollbar-thumb:hover {
  background: color-mix(in oklab, var(--color-primary) 35%, var(--color-border));
}

/* Round badge */
.harness-round {
  animation: harness-round-in 0.4s ease-out;
}
@keyframes harness-round-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
.harness-round-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  min-width: 30px;
  padding: 0 7px;
  border-radius: 4px;
  background: color-mix(in oklab, var(--color-primary) 10%, transparent);
  color: var(--color-primary);
  border: 1px solid color-mix(in oklab, var(--color-primary) 28%, transparent);
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  white-space: nowrap;
}
.harness-round-badge--active {
  background: color-mix(in oklab, var(--color-primary) 18%, transparent);
  box-shadow: 0 0 0 2px color-mix(in oklab, var(--color-primary) 12%, transparent);
}

/* Thought block */
.harness-thought {
  position: relative;
  padding-left: 14px;
  padding-right: 4px;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', 'SF Mono', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.72;
  color: color-mix(in oklab, var(--color-foreground) 88%, var(--color-muted-foreground));
  white-space: pre-wrap;
  word-break: break-word;
  margin-bottom: 8px;
}
.harness-thought-bar {
  position: absolute;
  left: 2px;
  top: 3px;
  bottom: 3px;
  width: 2px;
  border-radius: 1px;
  background: linear-gradient(
    to bottom,
    color-mix(in oklab, var(--color-primary) 55%, transparent),
    color-mix(in oklab, var(--color-primary) 18%, transparent),
    transparent
  );
}
.harness-thought-text {
  display: inline;
}
.harness-caret {
  display: inline-block;
  width: 6px;
  margin-left: 1.5px;
  color: var(--color-primary);
  font-weight: 700;
  transform: translateY(-1px);
  animation: harness-caret-blink 0.95s steps(2, end) infinite;
}
@keyframes harness-caret-blink {
  50% { opacity: 0; }
}

/* Tool call rows */
.harness-toolcall {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid color-mix(in oklab, var(--color-border) 80%, transparent);
  background: color-mix(in oklab, var(--color-muted) 60%, transparent);
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 11.5px;
  line-height: 1.55;
  transition: border-color 0.18s, background-color 0.18s, transform 0.18s;
  animation: harness-toolcall-in 0.34s cubic-bezier(0.22, 1, 0.36, 1) backwards;
}
.harness-toolcall:hover {
  border-color: color-mix(in oklab, var(--color-primary) 30%, var(--color-border));
  background: color-mix(in oklab, var(--color-muted) 85%, transparent);
}
@keyframes harness-toolcall-in {
  from { opacity: 0; transform: translateX(-6px); }
  to   { opacity: 1; transform: translateX(0); }
}
.harness-toolcall-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
  flex-shrink: 0;
}
.harness-toolcall-body {
  flex: 1;
  min-width: 0;
}
.harness-toolcall-code {
  display: block;
  font-family: inherit;
  font-size: inherit;
  word-break: break-word;
  color: color-mix(in oklab, var(--color-foreground) 80%, var(--color-muted-foreground));
}
.harness-tool-name {
  color: var(--color-primary);
  font-weight: 600;
}
.harness-tool-paren {
  color: color-mix(in oklab, var(--color-muted-foreground) 80%, transparent);
}
.harness-tool-args {
  color: color-mix(in oklab, var(--color-foreground) 75%, var(--color-muted-foreground));
}
.harness-toolcall-error {
  margin-top: 2px;
  font-size: 10.5px;
  color: #e11d48;
}

/* Banners */
.harness-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 11.5px;
  animation: harness-round-in 0.36s ease-out;
}
.harness-banner--done {
  background: color-mix(in oklab, #10b981 12%, transparent);
  border: 1px solid color-mix(in oklab, #10b981 38%, transparent);
  color: #047857;
}
.harness-banner--error {
  background: color-mix(in oklab, #f43f5e 10%, transparent);
  border: 1px solid color-mix(in oklab, #f43f5e 36%, transparent);
  color: #be123c;
}
.harness-banner__title {
  font-weight: 700;
  letter-spacing: 0.04em;
}
.harness-banner__detail {
  opacity: 0.78;
  font-size: 11px;
}
.harness-banner__time {
  margin-left: auto;
  font-size: 10px;
  opacity: 0.6;
  letter-spacing: 0.04em;
}

/* Ellipsis loader */
.harness-ellipsis::after {
  content: '';
  display: inline-block;
  width: 1em;
  text-align: left;
  animation: harness-ellipsis 1.3s steps(4, end) infinite;
}
@keyframes harness-ellipsis {
  0%        { content: ''; }
  25%       { content: '.'; }
  50%       { content: '..'; }
  75%, 100% { content: '...'; }
}

/* Dark theme tweaks */
:global([data-theme="dark"]) .harness-banner--done {
  color: #34d399;
}
:global([data-theme="dark"]) .harness-banner--error {
  color: #fb7185;
}
:global([data-theme="dark"]) .harness-toolcall-error {
  color: #fb7185;
}
</style>
