<script setup lang="ts">
import { computed, ref } from 'vue'
import Card from '@/components/ui/Card.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import Button from '@/components/ui/Button.vue'

export interface Column {
  key: string
  label: string
  width?: string
}

const props = withDefaults(defineProps<{
  columns: Column[]
  data: Record<string, any>[]
  loading?: boolean
  emptyText?: string
  pageSize?: number
}>(), {
  loading: false,
  emptyText: '暂无数据',
  pageSize: 10,
})

const currentPage = ref(1)

const totalPages = computed(() => Math.max(1, Math.ceil(props.data.length / props.pageSize)))

const pagedData = computed(() => {
  const start = (currentPage.value - 1) * props.pageSize
  return props.data.slice(start, start + props.pageSize)
})

function goPage(n: number) {
  currentPage.value = Math.max(1, Math.min(n, totalPages.value))
}
</script>

<template>
  <div class="space-y-3">
    <div class="overflow-x-auto">
      <table class="w-full caption-bottom text-sm">
        <thead class="[&_tr]:border-b">
          <tr class="border-b transition-colors hover:bg-muted/50">
            <th
              v-for="col in columns"
              :key="col.key"
              class="h-10 px-3 text-left align-middle font-medium text-muted-foreground"
              :style="col.width ? { width: col.width } : {}"
            >
              {{ col.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-if="loading">
            <tr v-for="i in 5" :key="'sk-' + i">
              <td v-for="col in columns" :key="col.key" class="p-3">
                <Skeleton class="h-4 w-full" />
              </td>
            </tr>
          </template>
          <template v-else-if="!data.length">
            <tr>
              <td :colspan="columns.length" class="p-8 text-center">
                <div class="text-muted-foreground">
                  <slot name="empty">
                    {{ emptyText }}
                  </slot>
                </div>
              </td>
            </tr>
          </template>
          <template v-else>
            <tr
              v-for="(row, ri) in pagedData"
              :key="ri"
              class="border-b transition-colors hover:bg-muted/50"
            >
              <td v-for="col in columns" :key="col.key" class="p-3 align-middle">
                <slot :name="col.key" :row="row" :index="ri">
                  {{ row[col.key] }}
                </slot>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <div v-if="totalPages > 1" class="flex items-center justify-center gap-3 pt-2 border-t">
      <Button variant="outline" size="sm" :disabled="currentPage <= 1" @click="goPage(currentPage - 1)">
        上一页
      </Button>
      <span class="text-sm text-muted-foreground">{{ currentPage }} / {{ totalPages }}（共 {{ data.length }} 条）</span>
      <Button variant="outline" size="sm" :disabled="currentPage >= totalPages" @click="goPage(currentPage + 1)">
        下一页
      </Button>
    </div>
  </div>
</template>
