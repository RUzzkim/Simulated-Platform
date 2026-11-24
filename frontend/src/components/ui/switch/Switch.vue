<script setup>
import { SwitchRoot, SwitchThumb } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  class: { type: null, default: '' }
})
const emits = defineEmits(['update:modelValue'])
</script>

<template>
  <SwitchRoot
    :model-value="props.modelValue"
    :disabled="props.disabled"
    data-slot="switch"
    :class="
      cn(
        'peer data-[state=checked]:bg-primary data-[state=unchecked]:bg-input focus-visible:border-ring focus-visible:ring-ring/50 inline-flex h-[1.15rem] w-8 shrink-0 cursor-pointer items-center rounded-full border border-transparent shadow-xs transition-all outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50',
        props.class
      )
    "
    @update:model-value="emits('update:modelValue', $event)"
  >
    <SwitchThumb
      data-slot="switch-thumb"
      class="bg-background pointer-events-none block size-4 rounded-full ring-0 transition-transform data-[state=checked]:translate-x-[calc(100%-2px)] data-[state=unchecked]:translate-x-0"
    />
  </SwitchRoot>
</template>