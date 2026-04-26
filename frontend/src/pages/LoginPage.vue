<template>
  <section class="card">
    <h2>登录</h2>
    <p class="sub">超管使用账号密码登录；普通用户请从 SSO 链接进入。</p>
    <div class="form">
      <label>用户名<input v-model="form.username" class="input" /></label>
      <label>密码<input v-model="form.password" class="input" type="password" /></label>
    </div>
    <div class="row">
      <button class="btn ok" @click="login">登录</button>
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
const form = reactive({ username: '', password: '' })

async function login() {
  try {
    const { data } = await api.post('/api/v1/auth/login', { username: form.username.trim(), password: form.password })
    localStorage.setItem('zhidang_token', data.token)
    msg.value = '登录成功'
    await router.push('/review')
  } catch (error) {
    msg.value = error?.response?.data?.detail || '登录失败'
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
