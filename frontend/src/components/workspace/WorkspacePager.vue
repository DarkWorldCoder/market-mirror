<template>
  <nav v-if="total" class="ws-result-pager" :aria-label="`${label} pages`">
    <span>{{ Math.min(total, page * size + 1) }}–{{ Math.min(total, (page + 1) * size) }} of {{ total }} {{ label }}</span>
    <div v-if="total > size"><button class="ws-btn" :aria-label="`Previous ${label}`" :disabled="page <= 0" @click="$emit('update:page', page - 1)">Previous</button><button class="ws-btn" :aria-label="`Next ${label}`" :disabled="(page + 1) * size >= total" @click="$emit('update:page', page + 1)">Next</button></div>
  </nav>
</template>
<script setup>
defineProps({ page: { type: Number, default: 0 }, size: { type: Number, default: 30 }, total: { type: Number, default: 0 }, label: { type: String, default: 'items' } })
defineEmits(['update:page'])
</script>
<style scoped>
.ws-result-pager { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 0; font-size: 12px; color: var(--muted); }.ws-result-pager > div { display: flex; gap: 7px; }
</style>
