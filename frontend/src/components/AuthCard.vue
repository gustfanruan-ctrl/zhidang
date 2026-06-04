<script setup lang="ts">
import Card from '@/components/ui/Card.vue'
import CardHeader from '@/components/ui/CardHeader.vue'
import CardTitle from '@/components/ui/CardTitle.vue'
import CardDescription from '@/components/ui/CardDescription.vue'
import CardContent from '@/components/ui/CardContent.vue'
import CardFooter from '@/components/ui/CardFooter.vue'

defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="flex items-center justify-center min-h-svh p-4 bg-muted/30">
    <Card class="w-full max-w-md mx-auto shadow-lg border-border/60">
      <CardHeader class="text-center pb-2">
        <div class="mx-auto mb-4 w-12 h-12 rounded-xl bg-primary flex items-center justify-center">
          <span class="text-primary-foreground font-bold text-lg">智</span>
        </div>
        <CardTitle class="text-xl">{{ title }}</CardTitle>
        <CardDescription v-if="description" class="mt-1.5">{{ description }}</CardDescription>
      </CardHeader>
      <CardContent class="pt-2">
        <slot />
      </CardContent>
      <CardFooter v-if="$slots.footer" class="flex-col">
        <slot name="footer" />
      </CardFooter>
    </Card>
  </div>
</template>
