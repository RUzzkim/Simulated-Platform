<script setup>
import { DropdownMenuItem } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  variant: { type: String, default: 'default' },
  inset: { type: Boolean, default: false },
  class: { type: null, default: '' }
})
const emits = defineEmits(['select'])
</script>

<template>
  <DropdownMenuItem
    data-slot="dropdown-menu-item"
    :data-variant="props.variant"
    :data-inset="props.inset ? '' : undefined"
    :disabled="props.disabled"
    :class="
      cn(
        'focus:bg-accent focus:text-accent-foreground relative flex cursor-default cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none',
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        'data-[inset]:pl-8',
        props.variant === 'destructive' &&
          'data-[variant=destructive]:text-destructive data-[variant=destructive]:focus:bg-destructive/10 data-[variant=destructive]:focus:text-destructive',
        props.class
      )
    "
    @select="emits('select', $event)"
  >
    <slot />
  </DropdownMenuItem>
</template>