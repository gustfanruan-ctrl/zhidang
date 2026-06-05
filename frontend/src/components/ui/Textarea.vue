<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '@/lib/utils'
import type { HTMLAttributes } from 'vue'

interface Props {
  modelValue?: string | number
  class?: HTMLAttributes['class']
  placeholder?: string
  disabled?: boolean
  rows?: number
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  rows: 4,
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
}>()

const modelProxy = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val ?? ''),
})
</script>

<template>
  <textarea
    v-model="modelProxy"
    :placeholder="placeholder"
    :disabled="disabled"
    :rows="rows"
    :class="cn(
      'flex w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-vertical',
      props.class,
    )"
  />
</template>
