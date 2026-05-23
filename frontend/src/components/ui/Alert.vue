<script setup lang="ts">
import { cn } from '@/lib/utils'

defineProps<{
  variant?: 'default' | 'destructive'
  class?: string
}>()
</script>

<template>
  <div
    :class="cn(
      'relative w-full rounded-lg border p-4 text-sm',
      variant === 'destructive'
        ? 'border-red-300 bg-red-50 text-red-700'
        : 'border-border bg-muted text-foreground',
      $props.class,
    )"
  >
    <slot />
  </div>
</template>
