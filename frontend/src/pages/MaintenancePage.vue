<template>
  <section class="card">
    <div class="head">
      <div>
        <h2>维护面板</h2>
        <p class="sub">超管可查看后台、LLM、简道云健康状态</p>
      </div>
      <button class="btn" :disabled="loading" @click="loadHealth">{{ loading ? '检查中...' : '刷新状态' }}</button>
    </div>

    <div class="grid">
      <article class="item" :class="healthClass(health.backend?.ok)">
        <h3>后台</h3>
        <p>{{ health.backend?.ok ? '正常' : '异常' }}</p>
        <div class="msg">{{ health.backend?.message || '-' }}</div>
        <div class="actions">
          <button class="btn minor" :disabled="testing.backend" @click="runTest('backend')">{{ testing.backend ? '测试中...' : '健康检查' }}</button>
        </div>
        <div class="test-msg">{{ testMessage.backend || ' ' }}</div>
      </article>
      <article class="item" :class="healthClass(health.llm?.ok)">
        <h3>LLM 连通性</h3>
        <p>{{ health.llm?.ok ? '正常' : '异常' }}</p>
        <div class="msg">{{ health.llm?.message || '-' }}</div>
        <div class="actions">
          <button class="btn minor" :disabled="testing.llm" @click="runTest('llm')">{{ testing.llm ? '测试中...' : '测试连接' }}</button>
          <button class="btn ghost" @click="goTo('/llm')">去配置</button>
        </div>
        <div class="test-msg">{{ testMessage.llm || ' ' }}</div>
      </article>
      <article class="item" :class="healthClass(health.jiandaoyun?.ok)">
        <h3>简道云连通性</h3>
        <p>{{ health.jiandaoyun?.ok ? '正常' : '异常' }}</p>
        <div class="msg">{{ health.jiandaoyun?.message || '-' }}</div>
        <div class="actions">
          <button class="btn minor" :disabled="testing.jiandaoyun" @click="runTest('jiandaoyun')">{{ testing.jiandaoyun ? '测试中...' : '测试连接' }}</button>
          <button class="btn ghost" @click="goTo('/config')">去配置</button>
        </div>
        <div class="test-msg">{{ testMessage.jiandaoyun || ' ' }}</div>
      </article>
    </div>

    <div class="footer">
      <span>总状态：{{ overallText }}</span>
      <span>更新时间：{{ updatedAt || '-' }}</span>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const loading = ref(false)
const updatedAt = ref('')
const testing = reactive({ backend: false, llm: false, jiandaoyun: false })
const testMessage = reactive({ backend: '', llm: '', jiandaoyun: '' })
const health = reactive({
  backend: { ok: null, message: '' },
  llm: { ok: null, message: '' },
  jiandaoyun: { ok: null, message: '' },
})

const overallText = computed(() => {
  const values = [health.backend.ok, health.llm.ok, health.jiandaoyun.ok]
  if (values.every((v) => v === true)) return '全部正常'
  if (values.some((v) => v === false)) return '存在异常项'
  return '未检查'
})

function healthClass(ok) {
  if (ok === true) return 'ok'
  if (ok === false) return 'bad'
  return 'unknown'
}

function goTo(path) {
  router.push(path)
}

async function runTest(module) {
  testing[module] = true
  testMessage[module] = '测试中...'
  try {
    if (module === 'backend') {
      const { data } = await api.get('/api/v1/health')
      testMessage[module] = data?.ok ? '测试通过：后台健康' : '测试失败：后台异常'
    } else if (module === 'llm') {
      const { data } = await api.post('/api/v1/admin/llm-config/test', { target: 'agent_a' })
      testMessage[module] = data?.success ? '测试通过：LLM 可调用' : '测试失败：LLM 调用异常'
    } else if (module === 'jiandaoyun') {
      const { data } = await api.post('/api/v1/admin/config/test', {})
      testMessage[module] = data?.success ? `测试通过：${data.message || '连接正常'}` : '测试失败：简道云异常'
    }
    await loadHealth()
  } catch (error) {
    const detail = error?.response?.data?.detail
    testMessage[module] = `测试失败：${typeof detail === 'string' ? detail : (error?.message || '未知错误')}`
  } finally {
    testing[module] = false
  }
}

async function loadHealth() {
  loading.value = true
  try {
    const { data } = await api.get('/api/v1/admin/maintenance/health')
    health.backend = data.checks?.backend || { ok: false, message: '无数据' }
    health.llm = data.checks?.llm || { ok: false, message: '无数据' }
    health.jiandaoyun = data.checks?.jiandaoyun || { ok: false, message: '无数据' }
    updatedAt.value = new Date(data.timestamp).toLocaleString()
  } catch (error) {
    health.backend = { ok: false, message: '维护接口请求失败' }
    health.llm = { ok: false, message: '维护接口请求失败' }
    health.jiandaoyun = { ok: false, message: '维护接口请求失败' }
    updatedAt.value = new Date().toLocaleString()
  } finally {
    loading.value = false
  }
}

onMounted(loadHealth)
</script>

<style scoped>
.card{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:var(--shadow)}
.head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.sub{color:var(--muted);margin:6px 0 0}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}
.item{border:1px solid var(--line);border-radius:14px;padding:12px;background:var(--surface-soft)}
.item h3{margin:0 0 6px}
.item p{margin:0 0 8px;font-weight:700}
.item .msg{color:var(--muted);font-size:13px}
.actions{display:flex;gap:8px;margin-top:10px}
.ok{border-color:#86efac;background:color-mix(in srgb, var(--ok) 12%, var(--surface-soft))}
.bad{border-color:#fca5a5;background:color-mix(in srgb, var(--danger) 12%, var(--surface-soft))}
.unknown{border-color:var(--line);background:var(--surface-soft)}
.btn{padding:10px 14px;border-radius:12px;border:0;background:var(--primary);color:#fff;cursor:pointer}
.minor{background:#0ea5e9}
.ghost{background:var(--surface-soft);color:var(--text)}
.test-msg{margin-top:8px;font-size:12px;color:var(--muted);min-height:18px}
.footer{display:flex;justify-content:space-between;color:var(--muted);font-size:13px;margin-top:12px}
@media (max-width: 1100px){.grid{grid-template-columns:1fr}.footer{display:grid;gap:6px}}
</style>
