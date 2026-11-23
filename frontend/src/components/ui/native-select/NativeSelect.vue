<script setup>
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-vue-next";

const props = defineProps({ class: { type: null, required: false } });
const model = defineModel({ type: [String, Number], default: "" });
</script>

<template>
  <div data-slot="native-select-wrapper" class="relative inline-flex">
    <select
      v-model="model"
      data-slot="native-select"
      :class="cn('border-input h-9 w-full appearance-none rounded-md border bg-transparent py-1 pr-8 pl-3 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:opacity-50', props.class)"
    >
      <slot />
    </select>
    <ChevronDown class="text-muted-foreground pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2" aria-hidden="true" />
  </div>
</template>
