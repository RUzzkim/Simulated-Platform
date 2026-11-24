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
  <textarea
    v-bind="$attrs"
    data-slot="textarea"
    :value="props.modelValue"
    :class="
      cn(
        'border-input placeholder:text-muted-foreground min-h-16 w-full rounded-md border bg-transparent px-3 py-2 text-base shadow-xs transition-[color,box-shadow] outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm',
        'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
        props.class
      )
    "
    @input="emits('update:modelValue', $event.target.value)"
  />
</template>