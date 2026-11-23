<template>
  <svg class="marketmirror-logo" viewBox="0 0 200 190" :width="size" :height="size" :aria-hidden="decorative ? 'true' : undefined" :role="decorative ? undefined : 'img'" :aria-label="decorative ? undefined : label" focusable="false" fill="currentColor">
    <path d="M14 14 95 62 58 99 95 127 14 176Z" />
    <path fill="#f3d64b" d="M107 70 186 16V72L146 96Z" />
    <path d="M146 99 186 75V176L108 128Z" />
  </svg>
</template>
<script setup>
defineProps({ size: { type: [Number, String], default: 32 }, decorative: { type: Boolean, default: true }, label: { type: String, default: 'MarketMirror' } })
</script>
<style scoped>
.marketmirror-logo { display: inline-block; flex-shrink: 0; vertical-align: middle; }
</style>
