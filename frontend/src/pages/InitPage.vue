<template>
  <AuthCard title="初始化管理员" description="首次使用请创建超级管理员账号">
    <div class="grid gap-4">
      <div class="grid gap-2">
        <Label for="init-username">用户名</Label>
        <Input id="init-username" v-model="form.username" placeholder="请输入用户名" />
      </div>
      <div class="grid gap-2">
        <Label for="init-display">显示名</Label>
        <Input id="init-display" v-model="form.display_name" placeholder="请输入显示名" />
      </div>
      <div class="grid gap-2">
        <Label for="init-password">密码</Label>
        <Input id="init-password" v-model="form.password" type="password" placeholder="请输入密码" />
      </div>
    </div>

    <Alert v-if="msg" :variant="msg.includes('成功') ? 'default' : 'destructive'" class="mt-4">{{ msg }}</Alert>

    <template #footer>
      <Button class="w-full" :disabled="initializing" @click="initSystem">
        <Loader2 v-if="initializing" class="h-4 w-4 mr-2 animate-spin" />
        {{ initializing ? '初始化中...' : '创建并进入登录' }}
      </Button>
    </template>
  </AuthCard>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Loader2 } from '@lucide/vue'
import { api } from '../api'
import AuthCard from '../components/AuthCard.vue'
import Alert from '../components/ui/Alert.vue'
import Button from '../components/ui/Button.vue'
import Input from '../components/ui/Input.vue'
import Label from '../components/ui/Label.vue'

const router = useRouter()
const msg = ref('')
const initializing = ref(false)
const form = reactive({ username: '', password: '', display_name: '' })

async function initSystem() {
  if (initializing.value) return
  initializing.value = true
  try {
    await api.post('/api/v1/system/init', { username: form.username.trim(), password: form.password, display_name: form.display_name.trim() })
    msg.value = '初始化成功，请登录'
    await router.push('/login')
  } catch (error) {
    msg.value = error?.response?.data?.detail || '初始化失败'
  } finally {
    initializing.value = false
  }
}
</script>
