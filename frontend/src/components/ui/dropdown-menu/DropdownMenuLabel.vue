<script setup>
import { DropdownMenuLabel } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps({
  inset: { type: Boolean, default: false },
  class: { type: null, default: '' }
})
</script>

<template>
  <DropdownMenuLabel
    data-slot="dropdown-menu-label"
    :data-inset="props.inset ? '' : undefined"
    :class="cn('px-2 py-1.5 text-sm font-medium data-[inset]:pl-8', props.class)"
  >
    <slot />
  </DropdownMenuLabel>
</template>