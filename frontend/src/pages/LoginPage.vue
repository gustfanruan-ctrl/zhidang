<template>
  <AuthCard title="登录" description="客户成功自动化平台">
    <div class="grid gap-4">
      <div class="grid gap-2">
        <Label for="username">用户名</Label>
        <Input id="username" v-model="form.username" placeholder="请输入用户名" />
      </div>
      <div class="grid gap-2">
        <Label for="password">密码</Label>
        <Input id="password" v-model="form.password" type="password" placeholder="请输入密码" />
      </div>
    </div>

    <Alert v-if="msg" variant="destructive" class="mt-4">{{ msg }}</Alert>

    <template #footer>
      <div class="grid gap-3 w-full">
        <Button class="w-full" :disabled="loggingIn" @click="login">
          <Loader2 v-if="loggingIn" class="h-4 w-4 mr-2 animate-spin" />
          {{ loggingIn ? '登录中...' : '登录' }}
        </Button>
        <div class="relative">
          <div class="absolute inset-0 flex items-center">
            <Separator class="w-full" />
          </div>
          <div class="relative flex justify-center text-xs">
            <span class="bg-card px-2 text-muted-foreground">或</span>
          </div>
        </div>
        <Button variant="outline" class="w-full" @click="ssoLogin">
          SSO 登录
        </Button>
      </div>
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
import Separator from '../components/ui/Separator.vue'

const router = useRouter()
const loggingIn = ref(false)
const msg = ref('')
const form = reactive({ username: '', password: '' })

async function login() {
  if (loggingIn.value) return
  loggingIn.value = true
  try {
    const { data } = await api.post('/api/v1/auth/login', { username: form.username.trim(), password: form.password })
    localStorage.setItem('zhidang_token', data.token)
    if (data.display_name) {
      localStorage.setItem('zhidang_display_name', data.display_name)
    }
    if (data.source) {
      localStorage.setItem('zhidang_source', data.source)
    }
    msg.value = '登录成功'
    setTimeout(() => { msg.value = '' }, 3000)
    const target = data.source === 'superadmin' ? '/review' : '/transcripts'
    await router.push(target)
  } catch (error) {
    msg.value = error?.response?.data?.detail || '登录失败'
    setTimeout(() => { msg.value = '' }, 3000)
  } finally {
    loggingIn.value = false
  }
}

function ssoLogin() {
  window.location.href = 'https://crm.finereporthelp.com/WebReport/decision/cas/login?service=https://47-98-102-197.sslip.io/api/v1/sso/bi-callback'
}
</script>
