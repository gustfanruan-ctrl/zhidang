<template>
  <div class="max-w-5xl mx-auto space-y-8">
    <!-- Page header -->
    <div>
      <h1 class="text-xl font-bold">跟进记录生成</h1>
      <p class="text-sm text-muted-foreground mt-1">上传会议内容，自动生成结构化跟进记录，审核后提交到简道云</p>
    </div>
    <div class="flex justify-end">
      <Button variant="outline" size="sm" class="h-8 text-xs" @click="templateEditorOpen = true">
        <Settings2 class="h-3.5 w-3.5 mr-1.5" />
        模板设置
      </Button>
    </div>
    <!-- Step indicator -->
    <div class="flex items-center justify-center gap-0 py-4">
      <template v-for="(step, idx) in steps" :key="step.num">
        <div class="flex flex-col items-center gap-2">
          <div
            class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-300"
            :class="currentStep > step.num
              ? 'bg-emerald-500 text-white'
              : currentStep === step.num
                ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20'
                : 'border-2 border-muted-foreground/25 text-muted-foreground'"
          >
            <Check v-if="currentStep > step.num" class="h-5 w-5" />
            <span v-else>{{ step.num }}</span>
          </div>
          <span
            class="text-xs font-medium transition-colors"
            :class="currentStep >= step.num ? 'text-foreground' : 'text-muted-foreground'"
          >{{ step.label }}</span>
        </div>
        <div
          v-if="idx < steps.length - 1"
          class="w-16 h-0.5 rounded-full transition-colors duration-300"
          :class="currentStep > step.num ? 'bg-emerald-500' : 'bg-muted-foreground/20'"
        />
      </template>
    </div>
    <!-- Step 0: Pick from existing records (optional shortcut) -->
    <Card v-if="currentStep <= 2 || !reviewData">
      <CardHeader class="pb-3">
        <div class="flex items-center justify-between flex-wrap gap-2">
          <div>
            <CardTitle class="text-base">从已有记录拼接（可选）</CardTitle>
            <CardDescription>勾选若干条转写或跟进记录，一键拼接到下方内容</CardDescription>
          </div>
          <div class="flex items-center gap-2">
            <div class="inline-flex rounded-lg border border-border p-0.5 bg-muted/30">
              <button
                class="px-3 py-1 text-xs font-medium rounded-md transition-colors"
                :class="sourceType === 'transcript' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'"
                @click="switchSourceType('transcript')"
              >会议转写</button>
              <button
                class="px-3 py-1 text-xs font-medium rounded-md transition-colors"
                :class="sourceType === 'followup' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'"
                @click="switchSourceType('followup')"
              >跟进记录</button>
            </div>
            <Badge v-if="selectedSourceIds.size > 0" variant="default">已选 {{ selectedSourceIds.size }}</Badge>
            <Button variant="ghost" size="sm" class="h-7 text-xs" @click="sourcePanelOpen = !sourcePanelOpen">
              <ChevronDown class="h-3.5 w-3.5 mr-1 transition-transform" :class="sourcePanelOpen ? '' : '-rotate-90'" />
              {{ sourcePanelOpen ? '收起' : '展开' }}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent v-if="sourcePanelOpen">
        <div v-if="loadingSource" class="text-sm text-muted-foreground py-6 text-center flex items-center justify-center gap-2">
          <Loader2 class="h-3.5 w-3.5 animate-spin" />
          加载中...
        </div>
        <div v-else-if="!sourceList.length" class="text-sm text-muted-foreground py-6 text-center">
          {{ sourceType === 'followup' ? '当前客户暂无跟进记录' : '暂无转写记录' }}
        </div>
        <div v-else>
          <div class="rounded-lg border border-border max-h-[260px] overflow-y-auto">
            <label
              v-for="item in sourceList"
              :key="item.id"
              class="flex items-start gap-3 px-3 py-2 border-b border-border/40 last:border-0 cursor-pointer hover:bg-muted/30 transition-colors"
              :class="{ 'bg-primary/5': selectedSourceIds.has(item.id) }"
            >
              <input
                type="checkbox"
                class="h-3.5 w-3.5 cursor-pointer accent-primary mt-1"
                :checked="selectedSourceIds.has(item.id)"
                @change="toggleSourceSelected(item.id)"
              />
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium truncate">{{ item.title || '未命名' }}</div>
                <div class="flex items-center gap-2 mt-0.5 flex-wrap">
                  <span class="text-xs text-muted-foreground truncate">{{ item.company_name || '-' }}</span>
                  <span class="text-xs text-muted-foreground/60">·</span>
                  <span class="text-xs text-muted-foreground/80 tabular-nums">{{ formatSourceDate(item.review_date || item.created_at) }}</span>
                </div>
              </div>
            </label>
          </div>
          <div class="mt-3 flex items-center justify-between flex-wrap gap-2">
            <span class="text-xs text-muted-foreground">
              <span v-if="selectedSourceIds.size === 0">未选中任何记录</span>
              <span v-else>将拼接 <span class="text-foreground font-medium">{{ selectedSourceIds.size }}</span> 条到下方"转写内容"</span>
            </span>
            <div class="flex gap-1.5">
              <Button variant="ghost" size="sm" class="h-7 text-xs" :disabled="selectedSourceIds.size === 0" @click="clearSourceSelection">清空</Button>
              <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="selectedSourceIds.size === 0" @click="applySelectedSources">
                <Plus class="h-3.5 w-3.5 mr-1" />拼接到内容
              </Button>
            </div>
          </div>
          <div v-if="appliedSources.length" class="mt-3 rounded-lg bg-primary/5 border border-primary/20 px-3 py-2">
            <div class="flex items-center gap-2 mb-1.5">
              <Check class="h-3.5 w-3.5 text-primary" />
              <span class="text-xs font-medium text-foreground">即将分析以下 {{ appliedSources.length }} 条记录：</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <Badge v-for="s in appliedSources" :key="s.id" variant="secondary" class="text-[11px] font-normal">
                {{ s.title || '未命名' }}
              </Badge>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
    <!-- Step 1: Input section -->
    <Card v-if="currentStep <= 2 || !reviewData">
      <CardHeader>
        <CardTitle class="text-base">上传与输入</CardTitle>
        <CardDescription>上传文件或粘贴转写内容</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
        <div class="space-y-1.5">
          <Label>当前客户</Label>
          <Input :model-value="companyName" readonly class="bg-muted/50" />
        </div>
        <div class="space-y-1.5">
          <Label>上传文件</Label>
          <div class="flex gap-5 items-start">
            <div class="flex-1">
              <div
                class="border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all"
                :class="isDragOver ? 'border-primary bg-primary/5 scale-[1.01]' : 'border-muted-foreground/20 hover:border-primary/40 hover:bg-muted/50'"
                @dragover.prevent="onDragOver"
                @dragleave.prevent="onDragLeave"
                @drop.prevent="onFileDrop"
                @click="triggerFileInput"
              >
                <input ref="fileInput" type="file" accept=".txt,.jpg,.jpeg,.png,.webp" class="hidden" @change="onFileSelect" />
                <div v-if="!uploadedFiles.length" class="space-y-2">
                  <Upload class="h-8 w-8 mx-auto text-muted-foreground/40" />
                  <p class="text-sm text-muted-foreground">点击或拖拽上传文件（支持多选）</p>
                  <p class="text-xs text-muted-foreground/60">支持 .txt, .jpg, .jpeg, .png, .webp</p>
                </div>
                <div v-else class="space-y-2">
                  <div v-for="(f, idx) in uploadedFiles" :key="idx" class="flex items-center justify-between bg-muted/50 rounded-lg px-4 py-3">
                    <div class="flex items-center gap-3">
                      <Image v-if="f.type === 'image'" class="h-5 w-5 text-muted-foreground" />
                      <FileText v-else class="h-5 w-5 text-muted-foreground" />
                      <span class="text-sm font-medium truncate max-w-[200px]">{{ f.name }}</span>
                      <span class="text-xs text-muted-foreground/60">{{ f.type === 'image' ? '图片' : '文本' }}</span>
                    </div>
                    <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" @click.stop="removeFile(idx)">
                      <X class="h-4 w-4 mr-1" />移除
                    </Button>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="uploadedFiles.filter(f => f.type === 'image').length" class="flex gap-2 flex-wrap">
              <img v-for="(f, idx) in uploadedFiles.filter(f => f.type === 'image')" :key="idx" :src="f.dataUrl" alt="预览" class="w-[120px] h-[80px] object-cover rounded-lg border border-border" />
            </div>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>转写内容</Label>
          <Textarea v-model="transcriptText" placeholder="粘贴会议转写内容，或上传 txt 文件自动填充..." rows="10" />
        </div>
        <Button @click="generateReview" :disabled="!canGenerate || generating" size="lg">
          <Loader2 v-if="generating" class="h-4 w-4 mr-2 animate-spin" />
          <Sparkles v-else class="h-4 w-4 mr-2" />
          {{ generating ? 'AI 生成中...' : '生成跟进记录' }}
        </Button>
      </CardContent>
    </Card>
    <!-- Step 2-3: Preview / Edit -->
    <Card v-if="reviewData">
      <CardHeader>
        <CardTitle class="text-base">跟进记录预览与编辑</CardTitle>
        <CardDescription>审核 AI 生成的内容，确认无误后提交</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <Label>跟进类型</Label>
            <SelectNative v-model="reviewData.follow_type" class="w-full">
              <option value="线上跟进">线上跟进</option>
              <option value="线下跟进">线下跟进</option>
              <option value="内部沟通">内部沟通</option>
            </SelectNative>
          </div>
          <div class="space-y-1.5">
            <Label>跟进日期</Label>
            <Input v-model="reviewData.review_date" type="date" />
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>跟进记录</Label>
          <Textarea v-model="reviewData.review_record" rows="12" />
        </div>
        <div class="space-y-1.5">
          <div class="flex items-center justify-between gap-2">
            <Label>关联预期（可选）</Label>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 px-2 text-[10px]"
              :disabled="yuqiLoading || !companyId"
              @click="loadCustomerYuqiOptions(companyId)"
            >
              <Loader2 v-if="yuqiLoading" class="h-3 w-3 mr-1 animate-spin" />
              刷新
            </Button>
          </div>
          <SelectNative v-model="reviewData.yuqi_id" class="w-full">
            <option value="">不关联</option>
            <option
              v-if="reviewData.yuqi_id && !hasReviewYuqiOption(reviewData.yuqi_id)"
              :value="reviewData.yuqi_id"
            >当前：{{ truncateLabel(selectedYuqiSummary || reviewData.yuqi_id) }}</option>
            <option v-for="opt in reviewYuqiOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
          </SelectNative>
          <p v-if="selectedYuqiSummary" class="text-xs text-muted-foreground break-words">已关联：{{ selectedYuqiSummary }}</p>
          <p v-else-if="yuqiLoading" class="text-xs text-muted-foreground">正在加载当前客户已有预期...</p>
          <p v-else-if="yuqiWarning" class="text-xs text-amber-600">{{ yuqiWarning }}</p>
          <p v-else-if="companyId && !reviewYuqiOptions.length" class="text-xs text-muted-foreground">当前客户暂无可关联预期</p>
        </div>
        <div class="space-y-1.5">
          <Label>客户方参与人</Label>
          <!-- Selected contact -->
          <div v-if="selectedContact" class="flex items-center justify-between bg-primary/5 border border-primary/20 rounded-lg px-3 py-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate">{{ selectedContact.cont_name }}</div>
              <div class="text-[10px] text-muted-foreground font-mono">{{ selectedContact.cont_id }}</div>
            </div>
            <Button variant="ghost" size="sm" class="h-6 w-6 p-0 text-muted-foreground hover:text-destructive" @click="selectedContactId = ''">
              <X class="h-3.5 w-3.5" />
            </Button>
          </div>
          <!-- Contact search -->
          <div class="flex gap-2">
            <Input v-model="contactKeyword" class="flex-1 h-8 text-xs" placeholder="搜索联系人..." @input="filterContacts" />
          </div>
          <!-- Contact list -->
          <div class="rounded-lg border border-border max-h-[160px] overflow-y-auto">
            <div v-if="!filteredContacts.length" class="text-xs text-muted-foreground py-3 text-center">暂无匹配联系人</div>
            <div v-for="c in pagedContacts" :key="c.cont_id"
                 class="px-3 py-1.5 text-xs border-b border-border/30 last:border-0 cursor-pointer hover:bg-muted/40 transition-colors"
                 :class="{ 'bg-primary/5 border-primary/20': selectedContactId === c.cont_id }"
                 @click="selectedContactId = c.cont_id">
              <span class="font-medium">{{ c.cont_name }}</span>
            </div>
          </div>
          <!-- Contact pagination -->
          <div v-if="filteredContacts.length > 20" class="flex items-center justify-between gap-1">
            <Button variant="ghost" size="sm" class="h-6 text-[10px]" :disabled="contactPage <= 1" @click="contactPage--">上一页</Button>
            <span class="text-[10px] text-muted-foreground">{{ contactPage }} / {{ Math.ceil(filteredContacts.length / 20) }}</span>
            <Button variant="ghost" size="sm" class="h-6 text-[10px]" :disabled="contactPage >= Math.ceil(filteredContacts.length / 20)" @click="contactPage++">下一页</Button>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>关联出差（可选）</Label>
          <div v-if="!taskList.length" class="text-xs text-muted-foreground py-2">当前客户暂无出差记录</div>
          <div v-else class="rounded-lg border border-border max-h-[160px] overflow-y-auto">
            <label v-for="t in taskList" :key="t.task_id" class="flex items-center gap-3 px-3 py-2 border-b border-border/40 last:border-0 cursor-pointer hover:bg-muted/30 transition-colors">
              <input type="checkbox" :value="t.task_id" v-model="selectedTaskIds" class="h-3.5 w-3.5 cursor-pointer accent-primary mt-0.5" />
              <div class="flex-1 min-w-0">
                <div class="text-sm truncate">{{ t.task_remarks || '无备注' }}</div>
                <div class="text-xs text-muted-foreground">{{ (t.task_predate || '').split(' ')[0] }}</div>
              </div>
            </label>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label>推送前方</Label>
          <div class="flex gap-6">
            <label class="flex items-center gap-2 cursor-pointer text-sm">
              <input type="radio" v-model="reviewData.if_tuisong" value="是" class="accent-primary"> 是
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-sm">
              <input type="radio" v-model="reviewData.if_tuisong" value="否" class="accent-primary"> 否
            </label>
          </div>
        </div>
        <div class="space-y-2">
          <Label>跟进标签</Label>
          <div class="overflow-x-auto rounded-lg border border-border">
            <table class="w-full caption-bottom text-sm">
              <thead>
                <tr class="border-b border-border bg-muted/30">
                  <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground">一级标签</th>
                  <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground">二级标签</th>
                  <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground">三级标签</th>
                  <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[80px]">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(tag, index) in reviewData.genjin_tags" :key="index" class="border-b border-border/50 last:border-0">
                  <td class="p-2">
                    <SelectNative v-model="tag.level1" class="w-full h-auto py-1 text-xs leading-snug" @update:model-value="updateTagLevel2(index)">
                      <option value="">请选择</option>
                      <option v-for="level1 in tagTree" :key="level1.level1" :value="level1.level1">{{ level1.level1 }}</option>
                    </SelectNative>
                  </td>
                  <td class="p-2">
                    <SelectNative v-model="tag.level2" class="w-full h-auto py-1 text-xs leading-snug" :disabled="!tag.level1" @update:model-value="updateTagLevel3(index)">
                      <option value="">请选择</option>
                      <option v-for="level2 in getLevel2Options(tag.level1)" :key="level2.label" :value="level2.label">{{ level2.label }}</option>
                    </SelectNative>
                  </td>
                  <td class="p-2">
                    <SelectNative v-model="tag.level3" class="w-full h-auto py-1 text-xs leading-snug" :disabled="!tag.level2">
                      <option value="">请选择</option>
                      <option v-for="level3 in getLevel3Options(tag.level1, tag.level2)" :key="level3" :value="level3">{{ level3 }}</option>
                    </SelectNative>
                  </td>
                  <td class="p-2">
                    <Button variant="ghost" size="sm" class="h-7 text-xs text-destructive hover:text-destructive" @click="removeTag(index)">
                      <Trash2 class="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <Button variant="outline" size="sm" @click="addTag">
            <Plus class="h-3.5 w-3.5 mr-1" />新增标签

          </Button>
        </div>
        <Button class="w-full bg-emerald-600 hover:bg-emerald-700 text-white" size="lg" :disabled="!canSubmit || submitting" @click="submitReview">
          <Send v-if="!submitting" class="h-4 w-4 mr-2" />
          <Loader2 v-else class="h-4 w-4 mr-2 animate-spin" />
          {{ submitting ? '提交中...' : '提交到简道云' }}
        </Button>
      </CardContent>
    </Card>
    <!-- Message toast -->
    <div v-if="message" class="fixed bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-xl z-50 text-sm shadow-lg max-w-[90vw] break-words transition-all" :class="{
      'bg-primary text-primary-foreground': messageType === 'info',
      'bg-emerald-600 text-white': messageType === 'success',
      'bg-destructive text-destructive-foreground': messageType === 'error',
    }">{{ message }}</div>
    <FollowupReviewTemplateEditor
      :open="templateEditorOpen"
      @close="templateEditorOpen = false"
      @saved="onTemplateSaved"
    />
  </div>
</template>
<script setup>
import { computed, onMounted, ref, reactive, watch } from 'vue'
import { Upload, FileText, Image, X, Check, Plus, Send, Sparkles, Trash2, Loader2, ChevronDown, Settings2 } from '@lucide/vue'
import { api } from '../api'
import { useCustomerStore } from '../stores/customer'
import { fetchTranscripts as fetchAllTranscripts } from '../api/operation'
import { fetchFollowupRecords } from '../api/followup-records'
import FollowupReviewTemplateEditor from '../components/FollowupReviewTemplateEditor.vue'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import CardDescription from '../components/ui/CardDescription.vue'
import CardContent from '../components/ui/CardContent.vue'
import Button from '../components/ui/Button.vue'
import Input from '../components/ui/Input.vue'
import Textarea from '../components/ui/Textarea.vue'
import Label from '../components/ui/Label.vue'
import SelectNative from '../components/ui/SelectNative.vue'
import Badge from '../components/ui/Badge.vue'
const steps = [
  { num: 1, label: '上传文件' },
  { num: 2, label: 'AI 生成' },
  { num: 3, label: '审核编辑' },
  { num: 4, label: '提交' },
]
const today = new Date().toISOString().split('T')[0]
const transcriptText = ref('')
const reviewData = ref(null)
const contactList = ref([])
const taskList = ref([])
const selectedContactId = ref("")
const contactKeyword = ref("")
const contactPage = ref(1)
const selectedTaskIds = ref([])
const tagTree = ref([])
const config = reactive({
  review_entry_id: '670a28334883adafb152a869',
  review_system_prompt: ''
})
const generating = ref(false)
const submitting = ref(false)
const showAdvanced = ref(false)
const message = ref('')
const messageType = ref('info')
const uploadedFiles = ref([])  // [{ name, dataUrl, type }]
const isDragOver = ref(false)
const currentStep = ref(1)
const todayDate = ref(today)
const fileInput = ref(null)
const customerStore = useCustomerStore()
const sourceType = ref('transcript') // 'transcript' | 'followup'
const sourceList = ref([])
const selectedSourceIds = ref(new Set())
const loadingSource = ref(false)
const sourcePanelOpen = ref(false)
const appliedSources = ref([])
const templateEditorOpen = ref(false)
const yuqiLoading = ref(false)
const yuqiWarning = ref('')
const customerYuqiItems = ref([])
async function loadSourceList() {
  loadingSource.value = true
  try {
    if (sourceType.value === 'followup') {
      const params = companyId.value ? { company_id: companyId.value } : {}
      const data = await fetchFollowupRecords(params)
      sourceList.value = data.items || []
    } else {
      const data = await fetchAllTranscripts()
      sourceList.value = data.items || []
    }
  } catch (e) {
    console.warn('加载来源列表失败', e)
    sourceList.value = []
  } finally {
    loadingSource.value = false
  }
}
function toggleSourceSelected(id) {
  const next = new Set(selectedSourceIds.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedSourceIds.value = next
}
function clearSourceSelection() {
  selectedSourceIds.value = new Set()
  appliedSources.value = []
}
async function applySelectedSources() {
  if (selectedSourceIds.value.size === 0) return
  const chosen = sourceList.value.filter(s => selectedSourceIds.value.has(s.id))
  const details = await Promise.all(chosen.map(async s => {
    if (s.raw_text) return s.raw_text
    try {
      const isFollowup = sourceType.value === "followup"
      const url = isFollowup ? "/api/v1/followup-records/" + s.id : "/api/v1/transcripts/" + s.id
      const resp = await api.get(url)
      return resp.data.raw_text || ""
    } catch (e) { return "" }
  }))
  const NL = String.fromCharCode(10)
  const parts = []
  for (let i = 0; i < chosen.length; i++) {
    const s = chosen[i]
    const title = s.title || s.id
    const company = s.company_name || ""
    const text = details[i] || s.raw_text_preview || ""
    if (text) parts.push("--- " + title + " (" + company + ") ---" + NL + text)
  }
  transcriptText.value = parts.join(NL + NL)
  appliedSources.value = chosen.map(s => ({ id: s.id, title: s.title, company_name: s.company_name }))
  currentStep.value = 1
  showMessage("已拼接 " + chosen.length + " 条来源到下方内容", "success")
}
function switchSourceType(t) {
  if (sourceType.value === t) return
  sourceType.value = t
  selectedSourceIds.value = new Set()
  appliedSources.value = []
  loadSourceList()
  loadContacts()
  loadTasks()
}
function formatSourceDate(d) {
  if (!d) return '-'
  try {
    return new Date(d).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return '-' }
}
const companyId = computed(() => customerStore.currentCustomer?.company_id || '')
const companyName = computed(() => customerStore.currentCustomer?.company_name || customerStore.currentCustomer?.com_name || '')
const hasImages = computed(() => uploadedFiles.value.some(f => f.type === 'image'))
const hasReviewInput = computed(() => transcriptText.value.trim() || hasImages.value)
const canGenerate = computed(() => hasReviewInput.value && companyName.value)
const canSubmit = computed(() => reviewData.value && reviewData.value.follow_type && reviewData.value.review_date && reviewData.value.review_record)
const reviewYuqiOptions = computed(() => customerYuqiItems.value
  .filter(row => row && row._id)
  .map(row => ({
    id: row._id,
    label: truncateLabel(yuqiSummary(row) || row._id, 56),
    summary: yuqiSummary(row),
  })))
const selectedYuqiSummary = computed(() => {
  const selectedId = reviewData.value?.yuqi_id || ''
  if (!selectedId) return ''
  return reviewYuqiOptions.value.find(opt => opt.id === selectedId)?.summary || ''
})
function resetReviewFlowState() {
  transcriptText.value = ''
  reviewData.value = null
  uploadedFiles.value = []
  selectedSourceIds.value = new Set()
  appliedSources.value = []
  selectedContactId.value = ''
  selectedTaskIds.value = []
  sourcePanelOpen.value = false
  currentStep.value = 1
  todayDate.value = new Date().toISOString().split('T')[0]
}
// File methods
function triggerFileInput() { fileInput.value?.click() }
function onDragOver() { isDragOver.value = true }
function onDragLeave() { isDragOver.value = false }
function onFileDrop(e) {
  isDragOver.value = false
  const files = e.dataTransfer?.files || []
  for (const f of files) handleFile(f)
}
function onFileSelect(e) {
  const files = e.target.files
  for (const f of files) handleFile(f)
  fileInput.value.value = ''
}
function validateFile(file) {
  const allowedTypes = ['.txt', '.jpg', '.jpeg', '.png', '.webp']
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  return allowedTypes.includes(ext)
}
function getFileType(file) {
  const ext = file.name.split('.').pop().toLowerCase()
  return ['jpg', 'jpeg', 'png', 'webp'].includes(ext) ? 'image' : 'text'
}
function handleFile(file) {
  if (!validateFile(file)) {
    showMessage('不支持的文件类型，请上传 .txt, .jpg, .jpeg, .png, .webp 文件', 'error')
    return
  }
  const ftype = getFileType(file)
  if (ftype === 'text') {
    const reader = new FileReader()
    reader.onload = (e) => {
      transcriptText.value = transcriptText.value ? transcriptText.value + '\n\n' + e.target.result : e.target.result
      uploadedFiles.value.push({ name: file.name, dataUrl: null, type: 'text' })
      showMessage('文本文件 "' + file.name + '" 读取成功', 'success')
      currentStep.value = 1
    }
    reader.onerror = () => showMessage('读取文本文件失败', 'error')
    reader.readAsText(file)
  } else {
    const reader = new FileReader()
    reader.onload = (e) => {
      uploadedFiles.value.push({ name: file.name, dataUrl: e.target.result, type: 'image' })
      showMessage('图片 "' + file.name + '" 上传成功', 'success')
      currentStep.value = 1
    }
    reader.readAsDataURL(file)
  }
}
function removeFile(idx) {
  const removed = uploadedFiles.value.splice(idx, 1)[0]
  if (removed && removed.type === 'text') {
    transcriptText.value = ''
  }
  currentStep.value = 1
}
// Tag methods
function truncateLabel(text, limit = 32) {
  const value = String(text || '').trim()
  return value.length <= limit ? value : value.slice(0, limit) + '...'
}
function yuqiSummary(row) {
  return String(row?.detail_brief || row?.['预期简述'] || row?.detail || row?._id || '').trim()
}
function hasReviewYuqiOption(id) {
  return reviewYuqiOptions.value.some(opt => opt.id === id)
}
async function loadCustomerYuqiOptions(companyIdValue) {
  const id = String(companyIdValue || '').trim()
  if (!id || id === 'demo') {
    customerYuqiItems.value = []
    yuqiWarning.value = ''
    return
  }
  yuqiLoading.value = true
  try {
    const resp = await api.get(`/api/v1/customers/${id}/yuqi`, { params: { limit: 100 } })
    customerYuqiItems.value = resp.data?.items || []
    yuqiWarning.value = resp.data?.warning || ''
  } catch (e) {
    customerYuqiItems.value = []
    yuqiWarning.value = e?.response?.data?.detail || '已有预期加载失败'
  } finally {
    yuqiLoading.value = false
  }
}
async function loadContacts() {
  if (!companyId.value) { contactList.value = []; return }
  try {
    const params = customerStore.currentCustomer?.com_id
      ? { com_id: customerStore.currentCustomer.com_id }
      : {}
    const { data } = await api.get(`/api/v1/customers/${companyId.value}/contacts`, { params })
    contactList.value = data.contacts || []
  } catch { contactList.value = [] }
}
async function loadTasks() {
  if (!companyId.value) { taskList.value = []; return }
  try {
    const params = customerStore.currentCustomer?.com_id
      ? { com_id: customerStore.currentCustomer.com_id }
      : {}
    const { data } = await api.get(`/api/v1/customers/${companyId.value}/tasks`, { params })
    taskList.value = data.tasks || []
  } catch { taskList.value = [] }
}
function onContactChange() { /* selectedContactId already updated by v-model */ }
const filteredContacts = computed(() => {
  const k = contactKeyword.value.trim().toLowerCase()
  return !k ? contactList.value : contactList.value.filter(c => (c.cont_name || "").toLowerCase().includes(k))
})
const pagedContacts = computed(() => {
  const start = (contactPage.value - 1) * 20
  return filteredContacts.value.slice(start, start + 20)
})
function filterContacts() { contactPage.value = 1 }
const selectedContact = computed(() => contactList.value.find(c => c.cont_id === selectedContactId.value) || null)
async function loadTagTree() {
  try {
    const response = await api.get('/api/v1/followup/tags')
    tagTree.value = Array.isArray(response.data) ? response.data : (response.data.tags || [])
  } catch (error) {
    console.error('初始化标签失败', error)
    tagTree.value = []
  }
}
function getLevel2Options(level1) {
  const level1Item = tagTree.value.find(item => item.level1 === level1)
  return level1Item ? level1Item.children : []
}
function getLevel3Options(level1, level2) {
  const level1Item = tagTree.value.find(item => item.level1 === level1)
  if (!level1Item) return []
  const level2Item = level1Item.children.find(item => item.label === level2)
  return level2Item ? level2Item.children : []
}
function findTagId(level1, level2) {
  const l1 = tagTree.value.find(item => item.level1 === level1)
  if (!l1) return ''
  const l2 = l1.children.find(item => item.label === level2)
  return l2?.tag_id || ''
}
function updateTagLevel2(index) {
  reviewData.value.genjin_tags[index].level2 = ''
  reviewData.value.genjin_tags[index].level3 = ''
  reviewData.value.genjin_tags[index].tag_id = ''
}
function updateTagLevel3(index) {
  reviewData.value.genjin_tags[index].level3 = ''
  const tag = reviewData.value.genjin_tags[index]
  tag.tag_id = findTagId(tag.level1, tag.level2)
}
function addTag() {
  if (!reviewData.value) return
  if (!reviewData.value.genjin_tags) reviewData.value.genjin_tags = []
  reviewData.value.genjin_tags.push({ level1: '', level2: '', level3: '', tag_id: '' })
}
function removeTag(index) {
  reviewData.value.genjin_tags.splice(index, 1)
}
// Config
async function loadConfig() {
  try {
    const response = await api.get('/api/v1/admin/config')
    if (response.data.field_mappings) {
      Object.assign(config, response.data.field_mappings)
    }
  } catch (error) {
    console.error('自定义配置失败', error)
  }
}
function onTemplateSaved(payload) {
  templateEditorOpen.value = false
  showMessage(payload?.customized ? '模板已保存' : '已恢复默认模板', 'success')
}
// Generate
async function generateReview() {
  if (!canGenerate.value) return
  generating.value = true
  message.value = ''
  currentStep.value = 2
  try {
    const response = await api.post('/api/v1/followup/generate', {
      input_type: hasImages.value ? 'screenshot' : 'text',
      images: uploadedFiles.value.filter(f => f.type === 'image').map(f => f.dataUrl),
      content: transcriptText.value || '请根据上传图片内容生成结构化跟进记录。',
      company_id: companyId.value,
      company_name: companyName.value
    })
    const raw = response.data
    if (raw?.error) throw new Error(raw.error)
    reviewData.value = {
      follow_type: raw.follow_type || raw.business_action || '',
      review_date: todayDate.value,
      review_record: raw.review_record || '',
      contact_names: raw.contact_names || raw.contact_person || '',
      if_tuisong: raw.if_tuisong || '否',
      genjin_tags: raw.genjin_tags || [],
      company_name: raw.company_name || companyName.value,
      yuqi_id: raw.yuqi_id || '',
    }
    await loadCustomerYuqiOptions(companyId.value)
    currentStep.value = 3
    showMessage('跟进记录生成成功，请审核后提交', 'success')
  } catch (error) {
    console.error('生成失败', error)
    const detail = error.response?.status === 413
      ? '上传图片过大，请压缩图片或减少张数后重试'
      : (error.response?.data?.detail || error.message)
    showMessage('生成失败：' + detail, 'error')
    currentStep.value = 1
  } finally {
    generating.value = false
  }
}
// Submit
async function submitReview() {
  if (!canSubmit.value) return
  submitting.value = true
  message.value = ''
  currentStep.value = 4
  try {
    const payload = {
      company_id: companyId.value,
      company_name: companyName.value,
      follower: reviewData.value.follower || '',
      follow_type: reviewData.value.follow_type,
      review_date: reviewData.value.review_date,
      review_record: reviewData.value.review_record,
      comid: customerStore.currentCustomer?.com_id || '',
      genjin_tags: reviewData.value.genjin_tags || [],
      contname: selectedContact.value?.cont_name || "",
      contid: selectedContact.value?.cont_id || "",
      selected_contact: selectedContact.value || null,
      selected_tasks: taskList.value.filter(t => selectedTaskIds.value.includes(t.task_id)),
      yuqi_id: reviewData.value.yuqi_id || '',
      yuqi_first_value: reviewData.value.yuqi_first_value || '',
      relevent_tag: reviewData.value.relevent_tag || []
    }
    await api.post('/api/v1/followup/submit', payload)
    resetReviewFlowState()
    showMessage('成功提交到简道云', 'success')
  } catch (error) {
    console.error('提交失败', error)
    showMessage('提交失败：' + (error.response?.data?.detail || error.message), 'error')
    currentStep.value = 3
  } finally {
    submitting.value = false
  }
}
function showMessage(text, type = 'info') {
  message.value = text
  messageType.value = type
  setTimeout(() => { message.value = '' }, 3000)
}
watch(() => customerStore.currentCustomer?.company_id, (id, prev) => {
  if (id === prev) return
  selectedSourceIds.value = new Set()
  appliedSources.value = []
  contactList.value = []
  taskList.value = []
  selectedContactId.value = ''
  selectedTaskIds.value = []
  customerYuqiItems.value = []
  yuqiWarning.value = ''
  if (reviewData.value) reviewData.value.yuqi_id = ''
  loadSourceList()
  loadContacts()
  loadTasks()
  loadCustomerYuqiOptions(id)
})

watch(
  () => selectedTaskIds.value.length,
  (count) => {
    if (!reviewData.value) return
    if (count > 0) {
      reviewData.value.follow_type = '线下跟进'
    }
  },
)

async function ensureCustomerContext() {
  if (customerStore.currentCustomer?.company_id) return
  customerStore.hydrateCurrentCustomer()
  if (customerStore.currentCustomer?.company_id) return

  const legacyCompanyId = localStorage.getItem('zhidang_company_id') || ''
  if (!legacyCompanyId) return

  try {
    if (!customerStore.customers.length) {
      await customerStore.fetchCustomers(false)
    }
    const selected = customerStore.customers.find((c) =>
      c.company_id === legacyCompanyId || c.com_id === legacyCompanyId
    )
    if (selected) {
      await customerStore.switchCustomer(selected, 'hydrate')
    }
  } catch {
    // Keep the review page usable even if the customer list refresh fails.
  }
}
onMounted(async () => {
  await ensureCustomerContext()
  await loadContacts()
  await loadTasks()
  await loadTagTree()
  await loadConfig()
  await loadSourceList()
  await loadCustomerYuqiOptions(companyId.value)
})
</script>
