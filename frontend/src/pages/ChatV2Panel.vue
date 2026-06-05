<template>
  <div class="flex flex-col gap-3 min-h-0" :class="embedded ? 'h-full' : 'h-[calc(100vh-8rem)]'">
    <component :is="embedded ? 'div' : Card" class="flex flex-col flex-1 min-h-0 overflow-hidden">
      <CardHeader v-if="!embedded" class="pb-3 border-b border-border/50">
        <div class="flex items-center justify-between gap-3">
          <CardTitle class="text-base flex items-center gap-2">
            <Sparkles class="h-4 w-4 text-primary" />
            权利地图 · Chat V2（视觉 Agent）
          </CardTitle>
          <div class="flex items-center gap-2 text-xs text-muted-foreground">
            <span v-if="customerStore.currentCustomer">
              {{ customerStore.currentCustomer.com_name || customerStore.currentCustomer.company_name || customerStore.currentCustomer.company_id }}
            </span>
            <Button variant="ghost" size="sm" class="h-7 text-xs" :disabled="chatStore.isLoading" @click="chatStore.reset()">
              清空对话
            </Button>
          </div>
        </div>
      </CardHeader>

      <div ref="messagesEl" class="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        <div v-if="!customerStore.currentCustomer" class="h-full flex items-center justify-center text-center">
          <div class="space-y-2">
            <User class="h-10 w-10 mx-auto text-muted-foreground/40" />
            <p class="text-sm text-muted-foreground">请先在侧边栏选择客户</p>
          </div>
        </div>

        <div v-else-if="!chatStore.messages.length && !chatStore.isLoading" class="h-full flex items-center justify-center text-center">
          <div class="space-y-2 max-w-md">
            <MessageSquare class="h-10 w-10 mx-auto text-muted-foreground/40" />
            <p class="text-sm text-muted-foreground">用具体指令调整权利地图</p>
            <p class="text-xs text-muted-foreground/60">
              例：「新建财务部，黄宇担任 CFO，纪成、张强向其汇报」<br />
              「把张强移到黄宇左边」「将纪成的节点放大一些」
            </p>
          </div>
        </div>

        <template v-for="(msg, idx) in chatStore.messages" :key="idx">
          <!-- User -->
          <div v-if="msg.role === 'user'" class="flex justify-end">
            <div class="bg-primary text-primary-foreground rounded-2xl rounded-br-md px-4 py-2.5 max-w-[80%]">
              <div class="text-[11px] font-semibold mb-1 opacity-70">我</div>
              <div class="text-sm whitespace-pre-wrap break-words">{{ msg.content }}</div>
            </div>
          </div>

          <!-- Assistant -->
          <div v-else class="flex justify-start">
            <div class="bg-muted rounded-2xl rounded-bl-md px-4 py-3 max-w-[85%] space-y-2">
              <div class="text-[11px] font-semibold mb-1 opacity-70">AI 助手</div>

              <div
                v-if="msg.content"
                class="text-sm whitespace-pre-wrap break-words"
              >{{ msg.content }}</div>

              <details v-if="msg.toolCalls?.length" class="text-xs">
                <summary class="cursor-pointer text-muted-foreground hover:text-foreground select-none">
                  工具调用 · {{ msg.toolCalls.length }} 次
                </summary>
                <ul class="mt-2 space-y-2">
                  <li v-for="(tc, ti) in msg.toolCalls" :key="ti" class="rounded-md bg-background/60 border border-border/60 p-2">
                    <div class="flex items-center gap-2">
                      <Badge variant="outline" class="text-[10px]">{{ tc.tool }}</Badge>
                      <Badge
                        v-if="tc.result"
                        :variant="tc.result.ok === false ? 'destructive' : 'secondary'"
                        class="text-[10px]"
                      >
                        {{ tc.result.ok === false ? '失败' : '成功' }}
                      </Badge>
                    </div>
                    <pre class="mt-1 text-[11px] whitespace-pre-wrap break-all font-mono leading-relaxed text-muted-foreground">参数：{{ formatJson(tc.args) }}</pre>
                    <pre v-if="tc.result" class="text-[11px] whitespace-pre-wrap break-all font-mono leading-relaxed text-muted-foreground">结果：{{ formatJson(tc.result) }}</pre>
                  </li>
                </ul>
              </details>

              <details v-if="msg.graphState" class="text-xs">
                <summary class="cursor-pointer text-muted-foreground hover:text-foreground select-none">
                  图状态 · {{ msg.graphState.nodes?.length || 0 }} 节点 / {{ msg.graphState.edges?.length || 0 }} 边
                </summary>
                <pre class="mt-2 text-[11px] whitespace-pre-wrap break-all font-mono leading-relaxed text-muted-foreground">{{ formatJson(msg.graphState) }}</pre>
              </details>

              <div v-if="msg.screenshotUrl" class="pt-1">
                <img
                  :src="msg.screenshotUrl"
                  alt="screenshot"
                  class="max-h-48 rounded-md border border-border/60 cursor-zoom-in"
                  @click="openImage(msg.screenshotUrl)"
                />
              </div>

              <div
                v-if="msg.done?.converged === false && msg.done?.fallback_message"
                class="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"
              >
                <AlertTriangle class="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
                <div class="flex-1 space-y-1.5">
                  <div class="whitespace-pre-wrap break-words">{{ msg.done.fallback_message }}</div>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-7 px-2 text-[11px] border-amber-400 text-amber-800 hover:bg-amber-100"
                    @click="focusInput"
                  >
                    <RotateCcw class="h-3 w-3" />
                    <span class="ml-1">重新描述</span>
                  </Button>
                </div>
              </div>

              <div
                v-if="msg.done && !msg.done?.error"
                class="text-[11px] text-muted-foreground/80 pt-1"
              >
                {{ messageSummary(msg) }}
              </div>
            </div>
          </div>
        </template>

        <!-- Streaming preview (while loading) -->
        <div v-if="chatStore.isLoading" class="flex justify-start">
          <div class="bg-muted/70 border border-dashed border-border rounded-2xl rounded-bl-md px-4 py-3 max-w-[85%] space-y-1.5">
            <div class="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Loader2 class="h-3 w-3 animate-spin" />
              <span>{{ chatStore.streamingStatus || 'AI 正在思考...' }}</span>
            </div>
            <div v-if="chatStore.streamingText" class="text-sm whitespace-pre-wrap break-words text-muted-foreground">
              {{ chatStore.streamingText }}
            </div>
            <Skeleton v-else class="h-3 w-32" />
          </div>
        </div>
      </div>

      <div class="border-t border-border/50 p-3 space-y-2 shrink-0">
        <div v-if="chatStore.lastError" class="text-xs text-destructive">
          {{ chatStore.lastError }}
        </div>
        <div
          v-if="showVagueWarning"
          class="flex items-start gap-2 text-xs px-3 py-2 rounded-md border border-amber-300 bg-amber-50 text-amber-800"
        >
          <AlertTriangle class="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
          <span>💡 建议描述具体需求，例如："将张强移到黄宇左侧"。继续发送也可以，但 AI 可能无法准确理解。</span>
        </div>
        <div v-if="!chatStore.isLoading && doneSummary" class="text-[11px] text-muted-foreground/70">
          {{ doneSummary }}
        </div>
        <div class="flex gap-2 items-end">
          <div ref="inputWrap" class="flex-1">
            <Textarea
              v-model="input"
              class="min-h-[60px]"
              :rows="2"
              placeholder="输入指令，按 Ctrl/Cmd+Enter 发送"
              :disabled="chatStore.isLoading || !customerStore.currentCustomer"
              @keydown="onTextareaKeydown"
            />
          </div>
          <Button
            size="sm"
            class="h-10 px-4"
            :disabled="chatStore.isLoading || !input.trim() || !customerStore.currentCustomer"
            @click="onSend"
          >
            <Send v-if="!chatStore.isLoading" class="h-4 w-4" />
            <Loader2 v-else class="h-4 w-4 animate-spin" />
            <span class="ml-1.5">{{ chatStore.isLoading ? '处理中' : '发送' }}</span>
          </Button>
        </div>

        <div v-if="showCommitBar" class="flex items-center justify-end gap-2 pt-1">
          <span class="text-xs text-muted-foreground mr-auto">
            <template v-if="isNotConverged">AI 未完全收敛，建议重新描述后再执行。</template>
            <template v-else>AI 已完成调整，请确认是否写入。</template>
          </span>
          <Button
            variant="outline"
            size="sm"
            class="h-9 px-3"
            :disabled="chatStore.isLoading"
            @click="onDiscard"
          >
            <X class="h-4 w-4" />
            <span class="ml-1.5">放弃</span>
          </Button>
          <Button
            size="sm"
            class="h-9 px-3"
            :class="isNotConverged ? 'border border-dashed border-amber-400 opacity-80' : ''"
            :title="isNotConverged ? 'AI 未完全收敛，建议先重新描述。如确认无误可继续执行。' : ''"
            :disabled="chatStore.isLoading"
            @click="onCommit"
          >
            <Check v-if="!chatStore.isLoading" class="h-4 w-4" />
            <Loader2 v-else class="h-4 w-4 animate-spin" />
            <span class="ml-1.5">执行</span>
          </Button>
        </div>
      </div>
    </component>

    <!-- Image lightbox -->
    <div
      v-if="previewImage"
      class="fixed inset-0 z-50 bg-black/80 flex items-center justify-center cursor-zoom-out p-6"
      @click="previewImage = ''"
    >
      <img :src="previewImage" alt="preview" class="max-w-full max-h-full rounded-lg shadow-2xl" />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { AlertTriangle, Check, Loader2, MessageSquare, RotateCcw, Send, Sparkles, User, X } from '@lucide/vue'
import { useCustomerStore } from '../stores/customer'
import { usePowerMapChatStore } from '../stores/powerMapChat'
import { discardChatV2 } from '../services/powerMapChatV2'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import Button from '../components/ui/Button.vue'
import Textarea from '../components/ui/Textarea.vue'
import Badge from '../components/ui/Badge.vue'
import Skeleton from '../components/ui/Skeleton.vue'

const props = defineProps({
  embedded: { type: Boolean, default: false },
  version: { type: String, default: null },
})

const customerStore = useCustomerStore()
const chatStore = usePowerMapChatStore()

const input = ref('')
const messagesEl = ref(null)
const inputWrap = ref(null)
const previewImage = ref('')

const VAGUE_KEYWORDS = ['挤', '乱', '难看', '丑', '不好看', '重新整理', '看起来', '调整一下']

const showVagueWarning = computed(() => {
  const t = input.value.trim()
  if (!t) return false
  if (t.length < 6) return true
  return VAGUE_KEYWORDS.some((kw) => t.includes(kw))
})

const showCommitBar = computed(
  () => chatStore.lastDone !== null && !!chatStore.currentSessionId,
)

const isNotConverged = computed(
  () => chatStore.lastDone?.converged === false,
)

const doneSummary = computed(() => {
  const d = chatStore.lastDone
  if (!d) return ''
  const rounds = d.rounds ?? 0
  const executed = d.executed ?? 0
  return `共 ${rounds} 轮，${executed} 次工具调用`
})

function messageSummary(msg) {
  const d = msg?.done
  if (!d) return ''
  const rounds = d.rounds ?? 0
  const executed = d.executed ?? 0
  return `共 ${rounds} 轮，${executed} 次工具调用`
}

function focusInput() {
  nextTick(() => {
    const wrap = inputWrap.value
    const el = wrap?.querySelector ? wrap.querySelector('textarea') : null
    if (el) el.focus()
  })
}

function formatJson(value) {
  if (value === null || value === undefined) return '-'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function openImage(url) {
  previewImage.value = url
}

function onTextareaKeydown(event) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    onSend()
  }
}

async function onSend() {
  const text = input.value.trim()
  if (!text) return
  if (!customerStore.currentCustomer) return
  input.value = ''
  await chatStore.sendMessage(customerStore.currentCustomer.company_id, text, { version: props.version })
}

async function onCommit() {
  const cid = customerStore.currentCustomer?.company_id
  if (!cid) return
  await chatStore.commit(cid)
}

async function onDiscard() {
  const cid = customerStore.currentCustomer?.company_id
  await chatStore.discard(cid)
}

async function scrollToBottom() {
  await nextTick()
  const el = messagesEl.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => [chatStore.messages.length, chatStore.streamingText, chatStore.streamingStatus],
  () => { scrollToBottom() },
)

watch(
  () => customerStore.currentCustomer?.company_id,
  (_newId, oldId) => {
    if (chatStore.currentSessionId && oldId) {
      const sid = chatStore.currentSessionId
      discardChatV2({ companyId: oldId, sessionId: sid }).catch(() => {})
    }
    chatStore.reset()
  },
)

function handleBeforeUnload(event) {
  if (chatStore.currentSessionId) {
    const cid = customerStore.currentCustomer?.company_id
    const sid = chatStore.currentSessionId
    if (cid) {
      discardChatV2({ companyId: cid, sessionId: sid, keepalive: true }).catch(() => {})
    }
    event.preventDefault()
    event.returnValue = ''
    return ''
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
})

onBeforeRouteLeave(() => {
  if (!chatStore.currentSessionId) return true
  const ok = window.confirm('当前修改尚未提交，离开将放弃修改。确定离开？')
  if (!ok) return false
  const cid = customerStore.currentCustomer?.company_id
  const sid = chatStore.currentSessionId
  if (cid) {
    discardChatV2({ companyId: cid, sessionId: sid }).catch(() => {})
  }
  chatStore.reset()
  return true
})
</script>
