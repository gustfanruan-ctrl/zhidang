<!-- Toast notification display -->
<script setup lang="ts">
import { cn } from '@/lib/utils'
import { useToast } from '@/composables/useToast'

const { toasts } = useToast()

function removeToast(id: string) {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      <TransitionGroup name="toast">
        <div
          v-for="t in toasts"
          :key="t.id"
          :class="cn(
            'pointer-events-auto rounded-lg border p-4 shadow-lg animate-in slide-in-from-right-full',
            t.variant === 'destructive'
              ? 'border-destructive/50 bg-destructive text-destructive-foreground'
              : 'border-border bg-card text-card-foreground',
          )"
        >
          <div class="flex items-start justify-between gap-2">
            <div class="grid gap-1">
              <p class="text-sm font-semibold">{{ t.title }}</p>
              <p v-if="t.description" class="text-sm opacity-90">{{ t.description }}</p>
            </div>
            <button class="shrink-0 rounded-md p-1 opacity-70 hover:opacity-100 transition-opacity" @click="removeToast(t.id)">
              <span class="text-lg leading-none">&times;</span>
            </button>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-enter-active { transition: all 0.3s ease-out; }
.toast-leave-active { transition: all 0.2s ease-in; }
.toast-enter-from { transform: translateX(100%); opacity: 0; }
.toast-leave-to { transform: translateX(100%); opacity: 0; }
</style>
