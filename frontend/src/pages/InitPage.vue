<template>
  <section class="card">
    <h2>系统初始化</h2>
    <p class="sub">首次使用请创建超级管理员账号。</p>
    <div class="form">
      <label>用户名<input v-model="form.username" class="input" /></label>
      <label>显示名<input v-model="form.display_name" class="input" /></label>
      <label>密码<input v-model="form.password" class="input" type="password" /></label>
    </div>
    <div class="row">
      <button class="btn ok" @click="initSystem">创建并进入登录</button>
    </div>
    <div class="msg">{{ msg }}</div>
  </section>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const msg = ref('')
const form = reactive({ username: '', password: '', display_name: '' })

async function initSystem() {
  try {
    await api.post('/api/v1/system/init', { username: form.username.trim(), password: form.password, display_name: form.display_name.trim() })
    msg.value = '初始化成功，请登录'
    await router.push('/login')
  } catch (error) {
    msg.value = error?.response?.data?.detail || '初始化失败'
  }
}
</script>

<style scoped>
.card{max-width:560px;margin:36px auto;background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:var(--shadow)}
.sub{color:var(--muted)}
.form{display:grid;gap:12px;margin-top:12px}
label{display:grid;gap:6px}
.input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--text)}
.row{display:flex;gap:10px;margin-top:14px}
.btn{padding:10px 14px;border-radius:12px;border:0;background:var(--surface-soft);color:var(--text);cursor:pointer}.ok{background:var(--primary);color:#fff}
.msg{margin-top:10px;color:var(--muted)}
</style>
