<script setup lang="ts">
import { cn } from '@/lib/utils'
import type { HTMLAttributes } from 'vue'

interface Props {
  class?: HTMLAttributes['class']
}
</script>

<template>
  <div :class="cn('animate-pulse rounded-md bg-muted', $props.class)">
    <slot />
  </div>
</template>
