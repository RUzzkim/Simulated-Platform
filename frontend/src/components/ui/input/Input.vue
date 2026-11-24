<script setup>
import { cn } from '@/lib/utils'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: [String, Number], default: undefined },
  class: { type: null, default: '' }
})
const emits = defineEmits(['update:modelValue'])
</script>

<template>
  <input
    v-bind="$attrs"
    data-slot="input"
    :value="props.modelValue"
    :class="
      cn(
        'border-input placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground flex h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm',
        'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
        props.class
      )
    "
    @input="emits('update:modelValue', $event.target.value)"
  />
</template>