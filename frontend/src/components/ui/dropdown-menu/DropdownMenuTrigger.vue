<script setup>
import { DropdownMenuTrigger } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps({
  as: { type: null, default: 'button' },
  asChild: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  class: { type: null, default: '' }
})
</script>

<template>
  <DropdownMenuTrigger
    data-slot="dropdown-menu-trigger"
    :as="props.as"
    :as-child="props.asChild"
    :disabled="props.disabled"
    :class="cn('outline-hidden', props.class)"
  >
    <slot />
  </DropdownMenuTrigger>
</template>