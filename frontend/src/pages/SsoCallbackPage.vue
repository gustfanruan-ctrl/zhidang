<template>
  <section class="card">
    <h2>SSO 回调处理中...</h2>
    <p>{{ msg }}</p>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'


const router = useRouter()
const msg = ref('正在同步登录信息')

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token')
  const st = params.get('st') || params.get('ticket')
  const sid = params.get('sid')

  // CAS SSO 回调：用 st 向智档后端换取 JWT
  if (st) {
    try {
      msg.value = '正在验证 CAS 登录...'
      window.location.href = '/api/v1/sso/cas-callback?st=' + st + '&sid=' + (sid || '');
    } catch (e) {
      msg.value = `CAS 登录失败：${e?.response?.data?.detail || e?.message || '未知错误'}`
      return
    }
  }

  // 传统 token 模式
  if (token) {
    localStorage.setItem('zhidang_token', token)
    msg.value = '登录完成，正在跳转'
    await router.replace('/chat')
    return
  }

  msg.value = '缺少登录参数'
})
</script>

<style scoped>
.card{max-width:560px;margin:36px auto;background:var(--surface,#fff);border:1px solid var(--line,#e5e7eb);border-radius:20px;padding:18px}
</style>
