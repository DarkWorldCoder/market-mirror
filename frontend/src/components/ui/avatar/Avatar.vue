<script setup>
import { computed } from "vue";
import { cn } from "@/lib/utils";

// Initials avatar (no images are stored for people), sized like shadcn's Avatar.
const props = defineProps({ name: { type: String, default: "" }, class: { type: null, required: false } });
const initials = computed(() => {
  const words = String(props.name || "?").replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((words[0]?.[0] || "?") + (words[1]?.[0] || "")).toUpperCase();
});
</script>

<template>
  <span data-slot="avatar" :class="cn('bg-muted text-foreground relative flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full text-xs font-medium', props.class)" aria-hidden="true">{{ initials }}</span>
</template>
