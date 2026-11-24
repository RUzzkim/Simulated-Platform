<script setup>
import { DialogTrigger } from 'reka-ui'

const props = defineProps({
  as: { type: null, default: 'button' },
  asChild: { type: Boolean, default: false },
  class: { type: null, default: '' }
})
</script>

<template>
  <DialogTrigger
    data-slot="dialog-trigger"
    :as="props.as"
    :as-child="props.asChild"
    :class="props.class"
  >
    <slot />
  </DialogTrigger>
</template>