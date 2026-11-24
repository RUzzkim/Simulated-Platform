<script setup>
import { DropdownMenuContent, DropdownMenuPortal } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: null, default: '' },
  side: { type: String, default: 'bottom' },
  sideOffset: { type: Number, default: 4 },
  align: { type: String, default: 'end' },
  alignOffset: { type: Number, default: 0 }
})
</script>

<template>
  <DropdownMenuPortal>
    <DropdownMenuContent
      v-bind="$attrs"
      data-slot="dropdown-menu-content"
      :side="props.side"
      :side-offset="props.sideOffset"
      :align="props.align"
      :align-offset="props.alignOffset"
      :class="
        cn(
          'bg-popover text-popover-foreground z-50 max-h-[var(--reka-dropdown-menu-content-available-height)] min-w-[8rem] overflow-x-hidden overflow-y-auto rounded-md border p-1 shadow-md',
          props.class
        )
      "
    >
      <slot />
    </DropdownMenuContent>
  </DropdownMenuPortal>
</template>