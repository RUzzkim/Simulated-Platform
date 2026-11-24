<script setup>
import { SelectIcon, SelectTrigger } from 'reka-ui'
import { ChevronDown } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: null, default: '' },
  size: { type: String, default: 'default' }
})
</script>

<template>
  <SelectTrigger
    v-bind="$attrs"
    data-slot="select-trigger"
    :class="
      cn(
        'border-input flex w-fit items-center justify-between gap-2 rounded-md border bg-transparent px-3 py-2 text-sm whitespace-nowrap shadow-xs transition-[color,box-shadow] outline-none',
        'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
        'disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1',
        props.size === 'sm' ? 'h-8' : 'h-9',
        props.class
      )
    "
  >
    <slot />
    <SelectIcon as-child>
      <ChevronDown class="size-4 shrink-0 opacity-50" />
    </SelectIcon>
  </SelectTrigger>
</template>