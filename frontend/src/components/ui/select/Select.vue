<script setup>
import { SelectRoot } from 'reka-ui'

const props = defineProps({
  modelValue: { type: null, default: undefined },
  open: { type: Boolean, default: undefined },
  disabled: { type: Boolean, default: false }
})
const emits = defineEmits(['update:modelValue', 'update:open'])
</script>

<template>
  <SelectRoot
    v-bind="$attrs"
    data-slot="select"
    :model-value="props.modelValue"
    :open="props.open"
    :disabled="props.disabled"
    @update:model-value="emits('update:modelValue', $event)"
    @update:open="emits('update:open', $event)"
  >
    <slot />
  </SelectRoot>
</template>