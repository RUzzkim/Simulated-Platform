<script setup>
import {
  SelectContent,
  SelectPortal,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectViewport
} from 'reka-ui'
import { ChevronDown, ChevronUp } from 'lucide-vue-next'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: null, default: '' },
  position: { type: String, default: 'popper' },
  side: { type: String, default: 'bottom' },
  sideOffset: { type: Number, default: 4 },
  align: { type: String, default: 'start' }
})
</script>

<template>
  <SelectPortal>
    <SelectContent
      v-bind="$attrs"
      data-slot="select-content"
      :position="props.position"
      :side="props.side"
      :side-offset="props.sideOffset"
      :align="props.align"
      :class="
        cn(
          'bg-popover text-popover-foreground relative z-50 max-h-96 min-w-[8rem] overflow-hidden rounded-md border shadow-md',
          props.position === 'popper' &&
            'data-[side=bottom]:translate-y-1 data-[side=top]:-translate-y-1',
          props.class
        )
      "
    >
      <SelectScrollUpButton class="flex items-center justify-center py-1">
        <ChevronUp class="size-4" />
      </SelectScrollUpButton>
      <SelectViewport
        :class="
          cn(
            'p-1',
            props.position === 'popper' &&
              'h-[var(--reka-select-trigger-height)] w-full min-w-[var(--reka-select-trigger-width)] scroll-my-1'
          )
        "
      >
        <slot />
      </SelectViewport>
      <SelectScrollDownButton class="flex items-center justify-center py-1">
        <ChevronDown class="size-4" />
      </SelectScrollDownButton>
    </SelectContent>
  </SelectPortal>
</template>