<template>
  <div class="grid">
    <section class="card">
      <h2>简道云配置</h2>
      <div class="form-grid" autocomplete="off">
        <label>简道云 API Key<input v-model="form.jiandaoyun_api_key" class="input" type="password" name="jiandaoyun-api-key" autocomplete="new-password" autocapitalize="off" autocorrect="off" spellcheck="false" data-lpignore="true" placeholder="留空不修改" @input="markSecretTouched('jiandaoyun')"></label>
        <label>Base URL<input v-model="form.jiandaoyun_base_url" class="input"></label>
        <label>app_id<input v-model="form.jiandaoyun_app_id" class="input"></label>
        <label>entry_id<input v-model="form.main_entry_id" class="input"></label>
        <label>客户主表 entry_id<input v-model="form.customer_main_entry_id" class="input" placeholder="677f..."></label>
        <label>预期表 entry_id<input v-model="form.yuqi_entry_id" class="input" placeholder="69e8..."></label>
        <label>场景表 entry_id<input v-model="form.changjing_entry_id" class="input" placeholder="69e8..."></label>
        <label>跟进记录表 entry_id（预留）<input v-model="form.followup_entry_id" class="input" placeholder="未来新增时填写"></label>
        <label>SSO 密钥<input v-model="form.sso_shared_secret" class="input"></label>
        <label>Token TTL（分钟）<input v-model.number="form.sso_token_ttl_minutes" class="input" type="number"></label>
        <label>Agent-A 最大轮次<input v-model.number="form.agent_a_max_rounds" class="input" type="number"></label>
        <label>Agent-B 最大轮次<input v-model.number="form.agent_b_max_rounds" class="input" type="number"></label>
        <label>数据保留天数<input v-model.number="form.data_retention_days" class="input" type="number"></label>
        <label>钉钉 App Key<input v-model="form.dingtalk_app_key" class="input"></label>
        <label>钉钉 App Secret<input v-model="form.dingtalk_app_secret" class="input" type="password" name="dingtalk-app-secret" autocomplete="new-password" autocapitalize="off" autocorrect="off" spellcheck="false" data-lpignore="true" @input="markSecretTouched('dingtalk')"></label>
        <label>钉钉 Agent ID<input v-model="form.dingtalk_agent_id" class="input"></label>
      </div>
      <label>字段映射 JSON<textarea v-model="fieldMappingsText" class="input"></textarea></label>
      <div class="row">
        <button class="btn" @click="testConnection">测试连接</button>
        <button class="btn ok" @click="save">保存配置</button>
      </div>
      <div class="msg">{{ msg }}</div>
    </section>

    <section class="card">
      <h2>说明</h2>
      <ul>
        <li>配置保存后立即生效</li>
        <li>API Key 仅前端配置，不要求在代码中写死</li>
        <li>支持字段映射 JSON 与 SSO / 钉钉基础参数</li>
      </ul>
      <pre>{{ preview }}</pre>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const form = ref({
  jiandaoyun_api_key: '', jiandaoyun_base_url: '', jiandaoyun_app_id: '', main_entry_id: '',
  customer_main_entry_id: '', yuqi_entry_id: '', changjing_entry_id: '', followup_entry_id: '',
  field_mappings: {}, sso_shared_secret: '', sso_token_ttl_minutes: 5, agent_a_max_rounds: 5, agent_b_max_rounds: 5, data_retention_days: 90, dingtalk_app_key: '', dingtalk_app_secret: '', dingtalk_agent_id: ''
})
const fieldMappingsText = ref('{}')
const msg = ref('')
const secretTouched = ref({ jiandaoyun: false, dingtalk: false })
const preview = computed(() => JSON.stringify(form.value, null, 2))

async function load() {
  const { data } = await api.get('/api/v1/admin/config')
  const mapping = data.field_mappings || {}
  const jdy = mapping.jiandaoyun || {}
  const forms = jdy.forms || {}
  form.value = {
    ...form.value,
    ...data,
    jiandaoyun_api_key: '',
    dingtalk_app_secret: '',
    customer_main_entry_id: forms['客户主表']?.entry_id || '',
    yuqi_entry_id: forms['预期表']?.entry_id || '',
    changjing_entry_id: forms['场景表']?.entry_id || '',
    followup_entry_id: forms['跟进记录表']?.entry_id || '',
  }
  secretTouched.value = { jiandaoyun: false, dingtalk: false }
  fieldMappingsText.value = JSON.stringify(mapping, null, 2)
}

function markSecretTouched(field) {
  if (field === 'jiandaoyun') secretTouched.value.jiandaoyun = true
  if (field === 'dingtalk') secretTouched.value.dingtalk = true
}

function buildMergedFieldMappings() {
  const current = JSON.parse(fieldMappingsText.value || '{}')
  const jiandaoyun = current.jiandaoyun || {}
  const forms = jiandaoyun.forms || {}
  forms['客户主表'] = { ...(forms['客户主表'] || {}), entry_id: form.value.customer_main_entry_id || '' }
  forms['预期表'] = { ...(forms['预期表'] || {}), entry_id: form.value.yuqi_entry_id || '' }
  forms['场景表'] = { ...(forms['场景表'] || {}), entry_id: form.value.changjing_entry_id || '' }
  forms['跟进记录表'] = { ...(forms['跟进记录表'] || {}), entry_id: form.value.followup_entry_id || '' }
  return {
    ...current,
    jiandaoyun: {
      ...jiandaoyun,
      app_id: form.value.jiandaoyun_app_id || jiandaoyun.app_id || '',
      forms,
    },
  }
}
async function save() {
  try {
    const mergedFieldMappings = buildMergedFieldMappings()
    const payload = {
      jiandaoyun_api_key: secretTouched.value.jiandaoyun ? form.value.jiandaoyun_api_key : '',
      jiandaoyun_base_url: form.value.jiandaoyun_base_url,
      jiandaoyun_app_id: form.value.jiandaoyun_app_id,
      main_entry_id: form.value.main_entry_id,
      sso_shared_secret: form.value.sso_shared_secret,
      sso_token_ttl_minutes: form.value.sso_token_ttl_minutes,
      agent_a_max_rounds: form.value.agent_a_max_rounds,
      agent_b_max_rounds: form.value.agent_b_max_rounds,
      data_retention_days: form.value.data_retention_days,
      dingtalk_app_key: form.value.dingtalk_app_key,
      dingtalk_app_secret: secretTouched.value.dingtalk ? form.value.dingtalk_app_secret : '',
      dingtalk_agent_id: form.value.dingtalk_agent_id,
      field_mappings: mergedFieldMappings,
    }
    const { data } = await api.put('/api/v1/admin/config', payload)
    msg.value = `保存成功：${data.success}`
    await load()
  } catch (error) {
    msg.value = `保存失败：${error?.response?.data?.detail || error?.message || '未知错误'}`
  }
}
async function testConnection() {
  try {
    const { data } = await api.post('/api/v1/admin/config/test', {})
    msg.value = data.message
  } catch (error) {
    msg.value = `测试失败：${error?.response?.data?.detail || error?.message || '未知错误'}`
  }
}

onMounted(load)
</script>

<style scoped>
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:var(--shadow)}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
label{display:grid;gap:6px;font-size:14px}
.input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--text)}
textarea.input{min-height:180px}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
.btn{padding:10px 14px;border-radius:12px;border:0;background:var(--surface-soft);color:var(--text);cursor:pointer}.ok{background:var(--primary);color:#fff}
pre{white-space:pre-wrap;background:var(--surface-soft);color:var(--text);padding:12px;border-radius:12px;border:1px solid var(--line)}
.msg{margin-top:10px;color:var(--muted)}
@media (max-width: 1100px){.grid,.form-grid{grid-template-columns:1fr}}
</style>
