<script setup>
import { DialogContent, DialogPortal } from 'reka-ui'
import { X } from 'lucide-vue-next'
import { cn } from '@/lib/utils'
import DialogClose from './DialogClose.vue'
import DialogOverlay from './DialogOverlay.vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  class: { type: null, default: '' },
  showClose: { type: Boolean, default: true }
})
</script>

<template>
  <DialogPortal>
    <DialogOverlay />
    <DialogContent
      v-bind="$attrs"
      data-slot="dialog-content"
      :class="
        cn(
          'bg-background fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border p-6 shadow-lg sm:max-w-lg',
          props.class
        )
      "
    >
      <slot />
      <DialogClose
        v-if="props.showClose"
        class="ring-offset-background focus:ring-ring absolute top-4 right-4 flex size-4 cursor-pointer appearance-none items-center justify-center rounded-xs border-0 bg-transparent p-0 opacity-70 transition-opacity hover:opacity-100 focus:ring-2 focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none"
      >
        <X class="size-4" />
        <span class="sr-only">关闭</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>