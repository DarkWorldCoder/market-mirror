<template>
  <div class="ws-skeleton" :class="variant" role="status" aria-live="polite">
    <span class="sr-only">{{ label }}</span>
    <template v-if="variant === 'cards'">
      <div class="ws-skeleton-cards" aria-hidden="true"><i v-for="n in 4" :key="n"></i></div>
      <i v-for="n in lines" :key="`l${n}`" class="ws-skeleton-line" aria-hidden="true" :style="{ width: widths[(n - 1) % widths.length] }"></i>
    </template>
    <div v-else-if="variant === 'block'" class="ws-skeleton-block" aria-hidden="true" :style="{ height: `${height}px` }"></div>
    <template v-else>
      <i v-for="n in lines" :key="n" class="ws-skeleton-line" aria-hidden="true" :style="{ width: widths[(n - 1) % widths.length] }"></i>
    </template>
  </div>
</template>
<script setup>
// A quiet placeholder in the shape of what is loading; screen readers hear the label instead.
defineProps({
  label: { type: String, default: 'Loading' },
  lines: { type: Number, default: 3 },
  variant: { type: String, default: 'lines' },   // lines | cards | block
  height: { type: Number, default: 220 }
})
const widths = ['92%', '78%', '64%', '86%', '52%']
</script>
<style scoped>
.ws-skeleton { display: grid; gap: 10px; padding: 4px 0; min-width: 0; }
.ws-skeleton i, .ws-skeleton-block { display: block; border-radius: 8px; background: color-mix(in srgb, var(--line) 45%, var(--panel-2)); animation: ws-skeleton-pulse 1.6s ease-in-out infinite; }
.ws-skeleton-line { height: 12px; }
.ws-skeleton-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; margin-bottom: 4px; }
.ws-skeleton-cards i { height: 58px; border-radius: 12px; }
.ws-skeleton-block { width: 100%; border-radius: 12px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@keyframes ws-skeleton-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .55; } }
@media (prefers-reduced-motion: reduce) { .ws-skeleton i, .ws-skeleton-block { animation: none; opacity: .8; } }
</style>
