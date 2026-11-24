<script setup>
import { Primitive } from 'reka-ui'
import { cn } from '@/lib/utils'
import { badgeVariants } from '.'

const props = defineProps({
  variant: { type: String, default: 'default' },
  as: { type: [String, Object], default: 'span' },
  asChild: { type: Boolean, default: false },
  class: { type: null, default: '' }
})
</script>

<template>
  <Primitive
    data-slot="badge"
    :as="as"
    :as-child="asChild"
    :class="cn(badgeVariants({ variant }), props.class)"
  >
    <slot />
  </Primitive>
</template>