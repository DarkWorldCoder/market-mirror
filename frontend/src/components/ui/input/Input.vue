<script setup>
import { cn } from "@/lib/utils";

const props = defineProps({ class: { type: null, required: false } });
const model = defineModel({ type: [String, Number], default: "" });
</script>

<template>
  <input
    v-model="model"
    data-slot="input"
    :class="cn('placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground border-input flex h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:border-destructive', props.class)"
  />
</template>
