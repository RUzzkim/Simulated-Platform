<script setup>
import { DropdownMenuGroup } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: null, default: '' }
})
</script>

<template>
  <DropdownMenuGroup data-slot="dropdown-menu-group" :class="cn(props.class)">
    <slot />
  </DropdownMenuGroup>
</template>