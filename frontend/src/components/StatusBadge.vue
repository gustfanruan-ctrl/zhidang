<script setup lang="ts">
import { computed } from 'vue'
import Badge from '@/components/ui/Badge.vue'

const props = defineProps<{
  status: string
  variant?: 'default' | 'secondary' | 'destructive' | 'outline'
}>()

const colorClass = computed(() => {
  const s = (props.status || '').toLowerCase()
  if (['ok', 'success', 'active', 'done', 'extraction_done', 'comparison_done', 'reviewed'].includes(s)) {
    return 'bg-green-100 text-green-700 border-green-300'
  }
  if (['error', 'bad', 'failed'].includes(s)) {
    return 'bg-red-100 text-red-700 border-red-300'
  }
  if (['pending', 'warning'].includes(s)) {
    return 'bg-amber-100 text-amber-700 border-amber-300'
  }
  if (['extracting', 'comparing', 'parsing', 'processing'].includes(s)) {
    return 'bg-blue-100 text-blue-700 border-blue-300'
  }
  return 'bg-gray-100 text-gray-600 border-gray-300'
})
</script>

<template>
  <Badge :variant="variant || 'outline'" :class="colorClass">
    <slot />
  </Badge>
</template>
