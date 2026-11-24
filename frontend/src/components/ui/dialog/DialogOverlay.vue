<script setup>
import { DialogOverlay } from 'reka-ui'
import { cn } from '@/lib/utils'

const props = defineProps({ class: { type: null, default: '' } })
</script>

<template>
  <DialogOverlay
    data-slot="dialog-overlay"
    :class="cn('fixed inset-0 z-50 bg-black/50', props.class)"
  />
</template>