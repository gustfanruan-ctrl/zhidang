<template>
  <div class="max-w-4xl mx-auto space-y-6">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-bold">用户管理</h1>
        <p class="text-sm text-muted-foreground mt-1">管理 CSM 账号，创建、禁用、重置密码</p>
      </div>
      <Button @click="openCreate"><Plus class="h-4 w-4 mr-1.5" />新建用户</Button>
    </div>

    <div class="flex gap-2">
      <Input v-model="search" class="flex-1 h-9 text-sm" placeholder="搜索用户名或显示名..." @keyup.enter="loadUsers" />
      <Button variant="outline" size="sm" :disabled="loading" @click="loadUsers">搜索</Button>
    </div>

    <Card>
      <div v-if="loading" class="p-10 text-center text-muted-foreground text-sm">加载中...</div>
      <table v-else class="w-full caption-bottom text-sm">
        <thead class="border-b border-border">
          <tr class="text-xs text-muted-foreground text-left">
            <th class="p-3 font-medium">用户名</th>
            <th class="p-3 font-medium">显示名</th>
            <th class="p-3 font-medium">角色</th>
            <th class="p-3 font-medium">集成ID</th>
            <th class="p-3 font-medium">状态</th>
            <th class="p-3 font-medium text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id" class="border-b border-border/40 hover:bg-muted/30">
            <td class="p-3 font-medium">{{ u.username }}</td>
            <td class="p-3 text-muted-foreground">{{ u.display_name || '-' }}</td>
            <td class="p-3">
              <Badge :variant="u.role === 'superadmin' ? 'default' : 'secondary'" class="text-[11px]">
                {{ u.role === 'superadmin' ? '超管' : '普通' }}
              </Badge>
            </td>
            <td class="p-3 text-muted-foreground font-mono text-xs">{{ u.integrate_id || '-' }}</td>
            <td class="p-3">
              <span class="text-xs" :class="u.is_active ? 'text-emerald-600' : 'text-muted-foreground'">{{ u.is_active ? '启用' : '禁用' }}</span>
            </td>
            <td class="p-3 text-right">
              <div class="flex items-center justify-end gap-1">
                <Button variant="ghost" size="sm" class="h-7 text-xs" @click="openEdit(u)">编辑</Button>
                <Button variant="ghost" size="sm" class="h-7 text-xs" @click="resetPassword(u)">重置密码</Button>
                <Button variant="ghost" size="sm" class="h-7 text-xs" :class="u.is_active ? 'text-destructive' : 'text-emerald-600'" @click="toggleActive(u)">{{ u.is_active ? '禁用' : '启用' }}</Button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="flex items-center justify-between p-3 border-t border-border">
        <span class="text-xs text-muted-foreground">共 {{ total }} 人</span>
        <div class="flex gap-1">
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="page <= 1" @click="page--; loadUsers()">上一页</Button>
          <span class="flex items-center px-2 text-xs text-muted-foreground">{{ page }} / {{ Math.ceil(total / 20) || 1 }}</span>
          <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="page >= Math.ceil(total / 20)" @click="page++; loadUsers()">下一页</Button>
        </div>
      </div>
    </Card>

    <!-- Create/Edit Modal -->
    <Teleport to="body">
      <Transition enter-active-class="transition duration-200 ease-out" enter-from-class="opacity-0" leave-active-class="transition duration-150 ease-in" leave-to-class="opacity-0">
        <div v-if="modalOpen" class="fixed inset-0 z-50 flex items-center justify-center">
          <div class="absolute inset-0 bg-black/40" @click="modalOpen = false" />
          <div class="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6 space-y-4">
            <div class="flex items-center justify-between">
              <h3 class="text-lg font-semibold">{{ editing ? '编辑用户' : '新建用户' }}</h3>
              <Button variant="ghost" size="icon" class="h-8 w-8" @click="modalOpen = false"><X class="h-4 w-4" /></Button>
            </div>
            <div class="space-y-3">
              <div class="space-y-1.5">
                <Label>用户名 *</Label>
                <Input v-model="form.username" :disabled="!!editing" class="h-9 text-sm" placeholder="登录用户名" />
              </div>
              <div class="space-y-1.5">
                <Label>显示名</Label>
                <Input v-model="form.display_name" class="h-9 text-sm" placeholder="如：Gust-张小洋" />
              </div>
              <div class="space-y-1.5">
                <Label>集成ID</Label>
                <Input v-model="form.integrate_id" class="h-9 text-sm" placeholder="简道云 username" />
              </div>
              <div class="space-y-1.5">
                <Label>角色</Label>
                <SelectNative v-model="form.role" class="w-full h-9 text-sm">
                  <option value="user">普通用户（数据过滤）</option>
                  <option value="superadmin">超管（查看全部数据）</option>
                </SelectNative>
              </div>
              <div v-if="!editing" class="space-y-1.5">
                <Label>密码 *</Label>
                <Input v-model="form.password" type="password" class="h-9 text-sm" placeholder="至少6位" />
              </div>
            </div>
            <div v-if="errMsg" class="text-xs text-destructive">{{ errMsg }}</div>
            <div class="flex justify-end gap-2 pt-2">
              <Button variant="outline" size="sm" @click="modalOpen = false">取消</Button>
              <Button size="sm" :disabled="saving" @click="save">{{ saving ? '保存中...' : editing ? '保存' : '创建' }}</Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Password result modal -->
    <Teleport to="body">
      <div v-if="pwResult" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/40" @click="pwResult = null" />
        <div class="relative bg-card border border-border/60 rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6 space-y-4">
          <h3 class="text-lg font-semibold">密码已重置</h3>
          <div class="bg-muted rounded-lg p-4 text-center font-mono text-lg select-all">{{ pwResult }}</div>
          <p class="text-xs text-muted-foreground">请将新密码发送给用户，关闭后将无法再次查看</p>
          <Button class="w-full" @click="pwResult = null">我知道了</Button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Plus, X } from '@lucide/vue'
import { api } from '../api'
import Card from '../components/ui/Card.vue'
import Button from '../components/ui/Button.vue'
import Input from '../components/ui/Input.vue'
import Label from '../components/ui/Label.vue'
import Badge from '../components/ui/Badge.vue'
import SelectNative from '../components/ui/SelectNative.vue'

const users = ref([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const loading = ref(false)
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)
const errMsg = ref('')
const pwResult = ref(null)

const form = reactive({ username: '', display_name: '', integrate_id: '', role: 'user', password: '' })

async function loadUsers() {
  loading.value = true
  try {
    const { data } = await api.get('/api/v1/admin/users', { params: { q: search.value, page: page.value, limit: 20 } })
    users.value = data.users || []
    total.value = data.total || 0
  } catch {} finally { loading.value = false }
}

function openCreate() {
  editing.value = null; errMsg.value = ''
  Object.assign(form, { username: '', display_name: '', integrate_id: '', role: 'user', password: '' })
  modalOpen.value = true
}

function openEdit(u) {
  editing.value = u; errMsg.value = ''
  Object.assign(form, { username: u.username, display_name: u.display_name || '', integrate_id: u.integrate_id || '', role: u.role || 'user', password: '' })
  modalOpen.value = true
}

async function save() {
  if (!form.username.trim()) { errMsg.value = '用户名必填'; return }
  if (!editing.value && !form.password) { errMsg.value = '密码必填'; return }
  saving.value = true; errMsg.value = ''
  try {
    if (editing.value) {
      await api.put(`/api/v1/admin/users/${editing.value.id}`, { display_name: form.display_name, integrate_id: form.integrate_id, role: form.role })
    } else {
      await api.post('/api/v1/admin/users', { ...form })
    }
    modalOpen.value = false; loadUsers()
  } catch (e) { errMsg.value = e?.response?.data?.detail || '操作失败' } finally { saving.value = false }
}

async function toggleActive(u) {
  try {
    await api.patch(`/api/v1/admin/users/${u.id}`, { is_active: !u.is_active })
    loadUsers()
  } catch {}
}

async function resetPassword(u) {
  try {
    const { data } = await api.post(`/api/v1/admin/users/${u.id}/reset-password`)
    pwResult.value = data.new_password
  } catch {}
}

onMounted(loadUsers)
</script>
