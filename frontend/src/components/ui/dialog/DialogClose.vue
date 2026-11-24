<script setup>
import { DialogClose } from 'reka-ui'

const props = defineProps({
  as: { type: null, default: 'button' },
  asChild: { type: Boolean, default: false },
  class: { type: null, default: '' }
})
</script>

<template>
  <DialogClose
    data-slot="dialog-close"
    :as="props.as"
    :as-child="props.asChild"
    :class="props.class"
  >
    <slot />
  </DialogClose>
</template>