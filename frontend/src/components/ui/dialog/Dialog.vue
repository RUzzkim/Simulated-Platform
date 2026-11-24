<script setup>
import { DialogRoot } from 'reka-ui'

const props = defineProps({
  open: { type: Boolean, default: undefined },
  modal: { type: Boolean, default: true }
})
const emits = defineEmits(['update:open'])
</script>

<template>
  <DialogRoot
    data-slot="dialog"
    :open="props.open"
    :modal="props.modal"
    @update:open="emits('update:open', $event)"
  >
    <slot />
  </DialogRoot>
</template>