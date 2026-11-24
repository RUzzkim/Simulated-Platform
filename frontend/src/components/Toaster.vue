<script setup>
import { CircleAlert, CircleCheck, Info, TriangleAlert } from 'lucide-vue-next'
import { toasts } from '@/lib/toast'

const STYLE = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  error: 'border-red-200 bg-red-50 text-red-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  info: 'border-slate-200 bg-white text-slate-900'
}
const ICON = {
  success: CircleCheck,
  error: CircleAlert,
  warning: TriangleAlert,
  info: Info
}
const styleOf = (type) => STYLE[type] || STYLE.info
const iconOf = (type) => ICON[type] || ICON.info
</script>

<template>
  <div class="pointer-events-none fixed top-4 left-1/2 z-[2000] flex -translate-x-1/2 flex-col items-center gap-2">
    <TransitionGroup
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="-translate-y-2 opacity-0"
      leave-active-class="transition duration-150 ease-in"
      leave-to-class="-translate-y-2 opacity-0"
    >
      <div
        v-for="item in toasts"
        :key="item.id"
        data-slot="toast"
        :class="['pointer-events-auto flex items-center gap-2 rounded-md border px-4 py-2 text-sm shadow-md', styleOf(item.type)]"
      >
        <component :is="iconOf(item.type)" class="size-4 shrink-0" />
        <span>{{ item.message }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>