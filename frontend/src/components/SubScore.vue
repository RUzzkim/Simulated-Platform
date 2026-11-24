<template>
  <div class="flex items-center gap-2">
    <div class="h-1.5 w-14 overflow-hidden rounded-full bg-slate-200">
      <div class="h-full rounded-full transition-all" :class="barClass" :style="{ width: pct }"></div>
    </div>
    <span class="text-xs tabular-nums" :class="textClass">{{ value }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 }
})

const pct = computed(() => `${Math.max(0, Math.min(100, props.value))}%`)
const barClass = computed(() => {
  if (props.value >= 90) return 'bg-emerald-500'
  if (props.value >= 75) return 'bg-lime-500'
  if (props.value >= 60) return 'bg-amber-500'
  return 'bg-red-500'
})
const textClass = computed(() => {
  if (props.value >= 75) return 'text-slate-600'
  if (props.value >= 60) return 'text-amber-600'
  return 'text-red-600'
})
</script>
