<template>
  <Teleport to="body">
    <div v-if="open" class="fixed bottom-16 left-[272px] z-40">
      <Card class="w-[360px] shadow-2xl border border-border/60 rounded-2xl">
        <CardHeader class="pb-2">
          <div class="flex items-center justify-between">
            <CardTitle class="text-base">📖 使用指南</CardTitle>
            <Button variant="ghost" size="icon" class="h-7 w-7" @click="$emit('close')"><X class="h-4 w-4" /></Button>
          </div>
        </CardHeader>
        <CardContent class="space-y-4 text-sm max-h-[500px] overflow-y-auto">
          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">🎯 选择客户</h4>
            <p class="text-muted-foreground text-xs">在左侧下拉框选择你负责的客户，所有操作都基于当前客户。</p>
          </div>
          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">📤 上传与分析</h4>
            <p class="text-muted-foreground text-xs">进入<strong>「上传」</strong>页面，上传会议录音/截图/文本，点击"分析"启动 AI 提取场景和预期，生成操作卡片。</p>
          </div>
          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">📝 生成跟进记录</h4>
            <p class="text-muted-foreground text-xs">进入<strong>「跟进记录生成」</strong>页面，上传文件或粘贴会议内容，选择联系人，AI 自动生成结构化跟进记录，审核后一键提交简道云。</p>
          </div>
          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">💬 对话查询</h4>
            <p class="text-muted-foreground text-xs">进入<strong>「对话」</strong>页面，加载客户档案后，用自然语言查询、修改客户数据。</p>
          </div>
          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">🗺️ 权利地图</h4>
            <p class="text-muted-foreground text-xs">进入<strong>「权利地图」</strong>页面，可视化查看和编辑客户组织架构图。</p>
          </div>
          <Separator />
          <p class="text-[11px] text-muted-foreground/70">💡 提示：所有操作前请先在侧边栏选择客户。可从设置中关闭此指南。</p>
        </CardContent>
      </Card>
    </div>
  </Teleport>
</template>

<script setup>
import { X } from '@lucide/vue'
import Card from './ui/Card.vue'
import CardHeader from './ui/CardHeader.vue'
import CardTitle from './ui/CardTitle.vue'
import CardContent from './ui/CardContent.vue'
import Button from './ui/Button.vue'
import Separator from './ui/Separator.vue'

defineProps({ open: Boolean })
defineEmits(['close'])
</script>
