<script setup>
import { DropdownMenuRoot } from 'reka-ui'

const props = defineProps({
  open: { type: Boolean, default: undefined },
  modal: { type: Boolean, default: true },
  dir: { type: String, default: undefined }
})
const emits = defineEmits(['update:open'])
</script>

<template>
  <DropdownMenuRoot
    v-bind="$attrs"
    data-slot="dropdown-menu"
    :open="props.open"
    :modal="props.modal"
    :dir="props.dir"
    @update:open="emits('update:open', $event)"
  >
    <slot />
  </DropdownMenuRoot>
</template>