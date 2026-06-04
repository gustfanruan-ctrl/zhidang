<template>
  <div class="flex items-center justify-center min-h-svh p-4 bg-muted/30">
    <Card class="w-full max-w-md mx-auto shadow-lg">
      <CardHeader class="text-center">
        <div class="mx-auto mb-4 w-12 h-12 rounded-xl bg-primary flex items-center justify-center">
          <span class="text-primary-foreground font-bold text-lg">智</span>
        </div>
        <CardTitle>SSO 登录</CardTitle>
        <CardDescription>正在同步登录信息</CardDescription>
      </CardHeader>
      <CardContent class="flex flex-col items-center gap-4 py-6">
        <div v-if="!msg.includes('失败') && !msg.includes('缺少')" class="flex flex-col items-center gap-3">
          <Loader2 class="h-8 w-8 animate-spin text-primary" />
          <p class="text-sm text-muted-foreground">{{ msg }}</p>
        </div>
        <Alert v-else variant="destructive" class="w-full">{{ msg }}</Alert>
      </CardContent>
    </Card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Loader2 } from '@lucide/vue'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import CardDescription from '../components/ui/CardDescription.vue'
import CardContent from '../components/ui/CardContent.vue'
import Alert from '../components/ui/Alert.vue'


const router = useRouter()
const msg = ref('正在同步登录信息')

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token')
  const st = params.get('st') || params.get('ticket')
  const sid = params.get('sid')

  if (st) {
    try {
      msg.value = '正在验证 CAS 登录...'
      window.location.href = '/api/v1/sso/cas-callback?st=' + st + '&sid=' + (sid || '');
    } catch (e) {
      msg.value = `CAS 登录失败：${e?.response?.data?.detail || e?.message || '未知错误'}`
      return
    }
  }

  if (token) {
    localStorage.setItem('zhidang_token', token)
    msg.value = '登录完成，正在跳转'
    await router.replace('/chat')
    return
  }

  msg.value = '缺少登录参数'
})
</script>
