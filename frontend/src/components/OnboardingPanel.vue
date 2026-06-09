<template>
  <Teleport to="body">
    <div v-if="open" class="fixed bottom-16 left-[272px] z-40">
      <Card class="w-[380px] shadow-2xl border border-border/60 rounded-2xl">
        <CardHeader class="pb-2">
          <div class="flex items-center justify-between">
            <CardTitle class="text-base">使用指南</CardTitle>
            <Button variant="ghost" size="icon" class="h-7 w-7" @click="$emit('close')">
              <X class="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent class="space-y-4 text-sm max-h-[520px] overflow-y-auto">
          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">1. 先选择客户</h4>
            <p class="text-muted-foreground text-xs leading-5">
              左侧先选中当前要维护的客户。对话、跟进记录、预期场景分析和权力地图，都会基于这个客户上下文执行。
            </p>
          </div>

          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">2. 对话维护客户档案</h4>
            <p class="text-muted-foreground text-xs leading-5">
              适合直接用自然语言维护客户档案。你可以查询、新增、修改、删除预期或场景；涉及写入时，系统会先给你预览，确认后才真正提交。
            </p>
          </div>

          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">3. 生成跟进记录</h4>
            <p class="text-muted-foreground text-xs leading-5">
              上传会议纪要、截图或粘贴沟通内容，AI 会生成结构化跟进记录。你可以在提交前补充跟进类型、日期、关联预期和出差信息，再写回简道云。
            </p>
          </div>

          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">4. 生成预期&amp;场景</h4>
            <p class="text-muted-foreground text-xs leading-5">
              上传会议转写或从已有跟进记录发起分析，系统会抽取客户预期和业务场景，生成待审核卡片。审核通过后，再同步写入客户档案。
            </p>
          </div>

          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">5. 权力地图维护</h4>
            <p class="text-muted-foreground text-xs leading-5">
              在这里查看和维护客户组织关系图。支持切换版本、查看节点连线，并通过对话方式调整人员、部门、关系和备注。
            </p>
          </div>

          <div>
            <h4 class="font-semibold text-xs text-primary mb-1">6. 推荐使用顺序</h4>
            <p class="text-muted-foreground text-xs leading-5">
              如果你刚完成一次客户沟通，通常可以先生成跟进记录，再生成预期&amp;场景；如果只是补录或修正已有档案，直接进入“对话维护客户档案”会更快。
            </p>
          </div>

          <Separator />
          <p class="text-[11px] text-muted-foreground/70 leading-5">
            提示：如果左侧没有选客户，大多数页面都会无法提交。这个指南入口可以在“设置”里关闭。
          </p>
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
