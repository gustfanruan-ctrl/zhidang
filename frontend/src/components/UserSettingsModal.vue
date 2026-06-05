<template>
  <Teleport to="body">
    <Transition enter-active-class="transition duration-200 ease-out" enter-from-class="opacity-0" leave-active-class="transition duration-150 ease-in" leave-to-class="opacity-0">
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/40" @click="$emit('close')" />
        <div class="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6 space-y-5">
          <div class="flex items-center justify-between">
            <h3 class="text-lg font-semibold">设置</h3>
            <Button variant="ghost" size="icon" class="h-8 w-8" @click="$emit('close')"><X class="h-4 w-4" /></Button>
          </div>

          <!-- Password reset -->
          <div class="space-y-3">
            <h4 class="text-sm font-medium">修改密码</h4>
            <Input v-model="oldPw" type="password" placeholder="旧密码" class="h-9 text-sm" />
            <Input v-model="newPw" type="password" placeholder="新密码（至少6位）" class="h-9 text-sm" />
            <Input v-model="confirmPw" type="password" placeholder="确认新密码" class="h-9 text-sm" />
            <div v-if="pwMsg" class="text-xs" :class="pwOk ? 'text-emerald-600' : 'text-destructive'">{{ pwMsg }}</div>
            <Button variant="outline" size="sm" :disabled="pwLoading" @click="changePassword">
              <Loader2 v-if="pwLoading" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
              确认修改
            </Button>
          </div>

          <Separator />

          <!-- Onboarding toggle -->
          <div class="flex items-center justify-between">
            <div>
              <h4 class="text-sm font-medium">新手引导</h4>
              <p class="text-xs text-muted-foreground">在左下角显示使用指南入口</p>
            </div>
            <button
              class="relative w-10 h-6 rounded-full transition-colors"
              :class="onboarding ? 'bg-primary' : 'bg-muted-foreground/30'"
              @click="toggleOnboarding"
            >
              <span class="absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-background shadow-sm transition-transform" :class="onboarding ? 'translate-x-4' : ''" />
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
import { X, Loader2 } from '@lucide/vue'
import Button from './ui/Button.vue'
import Input from './ui/Input.vue'
import Separator from './ui/Separator.vue'
import { api } from '../api'

const props = defineProps({ open: Boolean, onboarding: Boolean })
const emit = defineEmits(['close', 'update:onboarding'])

const oldPw = ref('')
const newPw = ref('')
const confirmPw = ref('')
const pwMsg = ref('')
const pwOk = ref(false)
const pwLoading = ref(false)

async function changePassword() {
  pwMsg.value = ''
  if (newPw.value.length < 6) { pwMsg.value = '新密码至少6位'; return }
  if (newPw.value !== confirmPw.value) { pwMsg.value = '两次密码不一致'; return }
  pwLoading.value = true
  try {
    await api.post('/api/v1/auth/change-password', { old_password: oldPw.value, new_password: newPw.value })
    pwOk.value = true
    pwMsg.value = '密码修改成功'
    oldPw.value = ''; newPw.value = ''; confirmPw.value = ''
  } catch (e) {
    pwOk.value = false
    pwMsg.value = e?.response?.data?.detail || '修改失败'
  } finally { pwLoading.value = false }
}

async function toggleOnboarding() {
  const next = !props.onboarding
  try {
    await api.patch('/api/v1/me/onboarding', { enabled: next })
    emit('update:onboarding', next)
  } catch {}
}
</script>
