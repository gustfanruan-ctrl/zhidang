<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '@/lib/utils'
import type { HTMLAttributes } from 'vue'

interface Props {
  modelValue?: string | number
  class?: HTMLAttributes['class']
  type?: string
  placeholder?: string
  disabled?: boolean
  min?: number | string
  max?: number | string
  step?: number | string
  readonly?: boolean
  autocomplete?: string
  autocapitalize?: string
  autocorrect?: string
  spellcheck?: string
  name?: string
  id?: string
}

const props = withDefaults(defineProps<Props>(), {
  type: 'text',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  input: [event: Event]
}>()

const modelProxy = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val ?? ''),
})
</script>

<template>
  <input
    v-model="modelProxy"
    :type="type"
    :placeholder="placeholder"
    :disabled="disabled"
    :min="min"
    :max="max"
    :step="step"
    :readonly="readonly"
    :autocomplete="autocomplete"
    :autocapitalize="autocapitalize"
    :autocorrect="autocorrect"
    :spellcheck="spellcheck"
    :name="name"
    :id="id"
    :class="cn(
      'flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
      props.class,
    )"
    @input="emit('input', $event)"
  >
</template>
