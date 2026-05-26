<template>
  <Teleport to="body">
    <Transition enter-active-class="transition duration-200 ease-out" enter-from-class="opacity-0" leave-active-class="transition duration-150 ease-in" leave-to-class="opacity-0">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/40" @click="$emit('close')" />
        <div class="relative bg-card border border-border/60 rounded-xl shadow-2xl w-full max-w-3xl mx-4 max-h-[86vh] flex flex-col">
          <div class="flex items-center justify-between gap-3 px-5 py-4 border-b border-border">
            <div class="min-w-0">
              <h3 class="text-lg font-semibold">跟进记录正文模板</h3>
              <p class="text-xs text-muted-foreground mt-1">配置正文段落，生成时会动态注入提示词</p>
            </div>
            <Button variant="ghost" size="icon" class="h-8 w-8 shrink-0" @click="$emit('close')">
              <X class="h-4 w-4" />
            </Button>
          </div>

          <div class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <div v-if="loading" class="py-10 text-sm text-muted-foreground text-center flex items-center justify-center gap-2">
              <Loader2 class="h-4 w-4 animate-spin" />
              加载模板...
            </div>
            <template v-else>
              <div class="flex items-center justify-between gap-3 flex-wrap">
                <div class="flex items-center gap-2">
                  <Badge :variant="customized ? 'default' : 'secondary'" class="text-[11px]">
                    {{ customized ? '自定义模板' : '默认模板' }}
                  </Badge>
                  <span class="text-xs text-muted-foreground">已启用 {{ enabledCount }} / {{ draftSections.length }} 段</span>
                </div>
                <div class="flex gap-2">
                  <Button variant="outline" size="sm" class="h-8 text-xs" :disabled="saving" @click="addSection">
                    <Plus class="h-3.5 w-3.5 mr-1" />新增段落
                  </Button>
                  <Button variant="ghost" size="sm" class="h-8 text-xs" :disabled="saving" @click="resetToDefault">
                    恢复默认
                  </Button>
                </div>
              </div>

              <div v-if="!editable" class="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                当前登录身份未绑定用户表账号，暂时只能使用默认模板。
              </div>

              <div class="space-y-3">
                <div
                  v-for="(section, index) in draftSections"
                  :key="section.localId"
                  class="rounded-lg border border-border bg-background p-4 space-y-3"
                  :class="section.enabled ? '' : 'opacity-60'"
                >
                  <div class="flex items-center justify-between gap-3">
                    <label class="flex items-center gap-2 text-sm font-medium cursor-pointer">
                      <input v-model="section.enabled" type="checkbox" class="h-4 w-4 accent-primary" />
                      段落 {{ index + 1 }}
                    </label>
                    <div class="flex items-center gap-1">
                      <Button variant="ghost" size="icon" class="h-7 w-7" :disabled="index === 0" title="上移" @click="moveSection(index, -1)">
                        <ArrowUp class="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" class="h-7 w-7" :disabled="index === draftSections.length - 1" title="下移" @click="moveSection(index, 1)">
                        <ArrowDown class="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" class="h-7 w-7 text-destructive hover:text-destructive" title="删除" @click="removeSection(index)">
                        <Trash2 class="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>

                  <div class="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-3">
                    <div class="space-y-1.5">
                      <Label>段落标题</Label>
                      <Input v-model="section.title" class="h-9 text-sm" placeholder="例如：整体Review" />
                    </div>
                    <div class="space-y-1.5">
                      <Label>生成要求</Label>
                      <Textarea
                        v-model="section.instruction"
                        rows="3"
                        placeholder="告诉 LLM 这一段需要识别和归纳什么"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="errorMessage" class="text-xs text-destructive">{{ errorMessage }}</div>
            </template>
          </div>

          <div class="flex items-center justify-end gap-2 px-5 py-4 border-t border-border">
            <Button variant="outline" size="sm" @click="$emit('close')">取消</Button>
            <Button size="sm" :disabled="saving || loading || !editable" @click="saveTemplate">
              <Loader2 v-if="saving" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
              保存模板
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Loader2, Plus, Trash2, X } from '@lucide/vue'
import { api } from '../api'
import Badge from './ui/Badge.vue'
import Button from './ui/Button.vue'
import Input from './ui/Input.vue'
import Label from './ui/Label.vue'
import Textarea from './ui/Textarea.vue'

const props = defineProps({
  open: Boolean,
})

const emit = defineEmits(['close', 'saved'])

const loading = ref(false)
const saving = ref(false)
const draftSections = ref([])
const defaultSections = ref([])
const customized = ref(false)
const editable = ref(true)
const errorMessage = ref('')
let localIdSeed = 0

const enabledCount = computed(() => draftSections.value.filter((section) => section.enabled).length)

function cloneSections(sections) {
  return (sections || []).map((section) => ({
    key: section.key || '',
    title: section.title || '',
    instruction: section.instruction || '',
    enabled: section.enabled !== false,
    localId: ++localIdSeed,
  }))
}

function serializeSections() {
  return draftSections.value.map((section, index) => ({
    key: section.key || `section_${index + 1}`,
    title: (section.title || '').trim(),
    instruction: (section.instruction || '').trim(),
    enabled: section.enabled !== false,
  }))
}

async function loadTemplate() {
  loading.value = true
  errorMessage.value = ''
  try {
    const { data } = await api.get('/api/v1/me/followup-review-template')
    draftSections.value = cloneSections(data.sections || [])
    defaultSections.value = cloneSections(data.sections || [])
    customized.value = Boolean(data.customized)
    editable.value = data.editable !== false
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || '模板加载失败'
  } finally {
    loading.value = false
  }
}

function addSection() {
  draftSections.value.push({
    key: '',
    title: '新段落',
    instruction: '',
    enabled: true,
    localId: ++localIdSeed,
  })
}

function removeSection(index) {
  draftSections.value.splice(index, 1)
}

function moveSection(index, delta) {
  const nextIndex = index + delta
  if (nextIndex < 0 || nextIndex >= draftSections.value.length) return
  const next = [...draftSections.value]
  const [item] = next.splice(index, 1)
  next.splice(nextIndex, 0, item)
  draftSections.value = next
}

async function resetToDefault() {
  saving.value = true
  errorMessage.value = ''
  try {
    const { data } = await api.put('/api/v1/me/followup-review-template', { use_default: true })
    draftSections.value = cloneSections(data.sections || [])
    defaultSections.value = cloneSections(data.sections || [])
    customized.value = Boolean(data.customized)
    emit('saved', data)
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || '恢复默认失败'
  } finally {
    saving.value = false
  }
}

async function saveTemplate() {
  const sections = serializeSections()
  if (!sections.length) {
    errorMessage.value = '至少保留一个段落'
    return
  }
  if (!sections.some((section) => section.enabled)) {
    errorMessage.value = '至少启用一个段落'
    return
  }
  const invalidIndex = sections.findIndex((section) => !section.title || !section.instruction)
  if (invalidIndex >= 0) {
    errorMessage.value = `第 ${invalidIndex + 1} 个段落需要填写标题和生成要求`
    return
  }

  saving.value = true
  errorMessage.value = ''
  try {
    const { data } = await api.put('/api/v1/me/followup-review-template', { sections })
    draftSections.value = cloneSections(data.sections || [])
    defaultSections.value = cloneSections(data.sections || [])
    customized.value = Boolean(data.customized)
    emit('saved', data)
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || '保存模板失败'
  } finally {
    saving.value = false
  }
}

watch(() => props.open, (open) => {
  if (open) loadTemplate()
})
</script>
