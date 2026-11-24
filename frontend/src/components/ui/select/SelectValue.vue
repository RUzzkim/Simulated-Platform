<script setup>
import { SelectValue } from 'reka-ui'

const props = defineProps({
  placeholder: { type: String, default: '' },
  class: { type: null, default: '' }
})
</script>

<template>
  <SelectValue
    data-slot="select-value"
    :placeholder="props.placeholder"
    :class="props.class"
  />
</template>