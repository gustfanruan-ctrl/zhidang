<template>
  <Toaster />
  <div class="space-y-6">
    <div>
      <h1 class="text-xl font-bold">简道云配置</h1>
      <p class="text-sm text-muted-foreground mt-1">配置简道云 API、权利地图及平台参数</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 简道云配置 -->
      <Card>
        <CardHeader>
          <CardTitle class="text-base">简道云 API</CardTitle>
          <CardDescription>配置连接参数与表单映射</CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4" autocomplete="off">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">API Key</span>
              <Input v-model="form.jiandaoyun_api_key" type="password" name="jiandaoyun-api-key" autocomplete="new-password" :autocapitalize="'off'" :autocorrect="'off'" :spellcheck="'false'" placeholder="留空不修改" @input="markSecretTouched('jiandaoyun')" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Base URL</span>
              <Input v-model="form.jiandaoyun_base_url" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">app_id</span>
              <Input v-model="form.jiandaoyun_app_id" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">entry_id</span>
              <Input v-model="form.main_entry_id" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">客户主表 entry_id</span>
              <Input v-model="form.customer_main_entry_id" placeholder="677f..." />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">预期表 entry_id</span>
              <Input v-model="form.yuqi_entry_id" placeholder="69e8..." />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">场景表 entry_id</span>
              <Input v-model="form.changjing_entry_id" placeholder="69e8..." />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">跟进记录表 entry_id</span>
              <Input v-model="form.followup_entry_id" placeholder="未来新增时填写" />
            </label>
          </div>

          <Separator />

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">SSO 密钥</span>
              <Input v-model="form.sso_shared_secret" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Token TTL（分钟）</span>
              <Input v-model.number="form.sso_token_ttl_minutes" type="number" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Agent-A 最大轮次</span>
              <Input v-model.number="form.agent_a_max_rounds" type="number" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">Agent-B 最大轮次</span>
              <Input v-model.number="form.agent_b_max_rounds" type="number" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">数据保留天数</span>
              <Input v-model.number="form.data_retention_days" type="number" />
            </label>
          </div>

          <Separator />

          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">钉钉 App Key</span>
              <Input v-model="form.dingtalk_app_key" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">钉钉 App Secret</span>
              <Input v-model="form.dingtalk_app_secret" type="password" name="dingtalk-app-secret" autocomplete="new-password" :autocapitalize="'off'" :autocorrect="'off'" :spellcheck="'false'" @input="markSecretTouched('dingtalk')" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">钉钉 Agent ID</span>
              <Input v-model="form.dingtalk_agent_id" />
            </label>
          </div>

          <Separator />

          <label class="flex flex-col gap-1.5">
            <span class="text-xs font-medium text-muted-foreground">字段映射 JSON</span>
            <Textarea v-model="fieldMappingsText" class="min-h-[180px] font-mono text-xs" />
          </label>

          <div class="flex gap-3 flex-wrap pt-2">
            <Button variant="secondary" size="sm" :disabled="testingConfig" @click="testConnection">
              <Loader2 v-if="testingConfig" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
              {{ testingConfig ? '测试中...' : '测试连接' }}
            </Button>
            <Button size="sm" :disabled="savingConfig" @click="save">
              <Loader2 v-if="savingConfig" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
              {{ savingConfig ? '保存中...' : '保存配置' }}
            </Button>
          </div>
        </CardContent>
      </Card>

      <!-- 权利地图配置 -->
      <Card>
        <CardHeader>
          <CardTitle class="text-base">权利地图</CardTitle>
          <CardDescription>FineReport BI 集成与代理认证</CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="grid grid-cols-1 gap-4" autocomplete="off">
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">API 地址</span>
              <Input v-model="form.power_map_base_url" placeholder="https://crm.finereporthelp.com/WebReport/decision" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">查询路径</span>
              <Input v-model="form.power_map_get_path" placeholder="/url/power_map/getInfo" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">更新路径</span>
              <Input v-model="form.power_map_update_path" placeholder="/url/power_map/upInfo" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">CAS 集成账号</span>
              <Input v-model="form.power_map_auth_token" type="password" name="power-map-auth-token" autocomplete="new-password" :autocapitalize="'off'" :autocorrect="'off'" :spellcheck="'false'" placeholder="可选，用于后端代理调用" @input="markSecretTouched('power_map')" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">BI 账密手机号</span>
              <Input v-model="form.power_map_login_mobile" placeholder="Gust" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="text-xs font-medium text-muted-foreground">BI 账密密码</span>
              <Input v-model="form.power_map_login_password" type="password" name="power-map-login-password" autocomplete="new-password" :autocapitalize="'off'" :autocorrect="'off'" :spellcheck="'false'" placeholder="留空不修改" @input="markSecretTouched('power_map_login')" />
            </label>
          </div>
        </CardContent>
      </Card>

      <!-- 说明 -->
      <Card class="lg:col-span-2">
        <CardHeader>
          <CardTitle class="text-base">配置说明</CardTitle>
        </CardHeader>
        <CardContent>
          <ul class="list-disc pl-5 space-y-1 text-sm text-muted-foreground">
            <li>配置保存后立即生效</li>
            <li>API Key 仅前端配置，不要求在代码中写死</li>
            <li>支持字段映射 JSON 与 SSO / 钉钉基础参数</li>
          </ul>
          <pre class="mt-4 whitespace-pre-wrap bg-muted text-muted-foreground p-3 rounded-lg border text-xs font-mono max-h-[300px] overflow-auto">{{ preview }}</pre>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Loader2 } from '@lucide/vue'
import { api } from '../api'
import { useToast } from '../composables/useToast'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import CardDescription from '../components/ui/CardDescription.vue'
import CardContent from '../components/ui/CardContent.vue'
import Input from '../components/ui/Input.vue'
import Textarea from '../components/ui/Textarea.vue'
import Button from '../components/ui/Button.vue'
import Separator from '../components/ui/Separator.vue'
import Toaster from '../components/ui/Toaster.vue'

const { toast } = useToast()

const form = ref({
  jiandaoyun_api_key: '', jiandaoyun_base_url: '', jiandaoyun_app_id: '', main_entry_id: '',
  customer_main_entry_id: '', yuqi_entry_id: '', changjing_entry_id: '', followup_entry_id: '',
  field_mappings: {}, sso_shared_secret: '', sso_token_ttl_minutes: 5, agent_a_max_rounds: 5, agent_b_max_rounds: 5, data_retention_days: 90, dingtalk_app_key: '', dingtalk_app_secret: '', dingtalk_agent_id: '',
  power_map_base_url: '', power_map_get_path: '', power_map_update_path: '', power_map_auth_token: '', power_map_login_mobile: '', power_map_login_password: ''
})
const fieldMappingsText = ref('{}')
const msg = ref('')
const secretTouched = ref({ jiandaoyun: false, dingtalk: false, power_map: false, power_map_login: false })
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
  secretTouched.value = { jiandaoyun: false, dingtalk: false, power_map: false, power_map_login: false }
  fieldMappingsText.value = JSON.stringify(mapping, null, 2)
  form.value.power_map_base_url = data.power_map_base_url || ''
  form.value.power_map_get_path = data.power_map_get_path || ''
  form.value.power_map_update_path = data.power_map_update_path || ''
  form.value.power_map_auth_token = ''
  form.value.power_map_login_mobile = data.power_map_login_mobile || ''
  form.value.power_map_login_password = ''
}

function markSecretTouched(field) {
  if (field === 'jiandaoyun') secretTouched.value.jiandaoyun = true
  if (field === 'dingtalk') secretTouched.value.dingtalk = true
  if (field === 'power_map') secretTouched.value.power_map = true
  if (field === 'power_map_login') secretTouched.value.power_map_login = true
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
const savingConfig = ref(false)
const testingConfig = ref(false)

async function save() {
  if (savingConfig.value) return
  savingConfig.value = true
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
      power_map_base_url: form.value.power_map_base_url,
      power_map_get_path: form.value.power_map_get_path,
      power_map_update_path: form.value.power_map_update_path,
      power_map_auth_token: secretTouched.value.power_map ? form.value.power_map_auth_token : '',
      power_map_login_mobile: form.value.power_map_login_mobile,
      power_map_login_password: secretTouched.value.power_map_login ? form.value.power_map_login_password : '',
      field_mappings: mergedFieldMappings,
    }
    const { data } = await api.put('/api/v1/admin/config', payload)
    toast({ title: '保存成功', description: data.success, variant: 'default' })
    await load()
  } catch (error) {
    toast({ title: '保存失败', description: error?.response?.data?.detail || error?.message || '未知错误', variant: 'destructive' })
  } finally {
    savingConfig.value = false
  }
}
async function testConnection() {
  if (testingConfig.value) return
  testingConfig.value = true
  try {
    const { data } = await api.post('/api/v1/admin/config/test', {})
    toast({ title: '测试结果', description: data.message, variant: 'default' })
  } catch (error) {
    toast({ title: '测试失败', description: error?.response?.data?.detail || error?.message || '未知错误', variant: 'destructive' })
  } finally {
    testingConfig.value = false
  }
}

onMounted(load)
</script>
