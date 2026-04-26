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
  const token = new URLSearchParams(window.location.search).get('token')
  if (token) localStorage.setItem('zhidang_token', token)
  msg.value = '登录完成，正在跳转'
  await router.replace('/chat')
})
</script>

<style scoped>
.card{max-width:560px;margin:36px auto;background:#fff;border:1px solid #e5e7eb;border-radius:20px;padding:18px}
</style>
