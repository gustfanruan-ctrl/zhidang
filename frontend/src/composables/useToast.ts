import { ref } from 'vue'

export interface Toast {
  id: string
  title: string
  description?: string
  variant?: 'default' | 'destructive'
  duration?: number
}

const toasts = ref<Toast[]>([])
let counter = 0

export function useToast() {
  function toast(opts: { title: string; description?: string; variant?: 'default' | 'destructive'; duration?: number }) {
    const id = `toast-${++counter}`
    const t: Toast = { id, ...opts, duration: opts.duration ?? 4000 }
    toasts.value = [...toasts.value, t]
    setTimeout(() => {
      toasts.value = toasts.value.filter((x) => x.id !== id)
    }, t.duration)
  }
  return { toast, toasts }
}
