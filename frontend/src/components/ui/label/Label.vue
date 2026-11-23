<script setup>
import { cn } from "@/lib/utils";

const props = defineProps({ class: { type: null, required: false }, for: { type: String, required: false } });
</script>

<template>
  <label data-slot="label" :for="props.for" :class="cn('flex items-center gap-2 text-sm leading-none font-medium select-none peer-disabled:cursor-not-allowed peer-disabled:opacity-50', props.class)">
    <slot />
  </label>
</template>
