<template>
  <section v-if="files.length" class="uploaded-context" aria-label="Attached files">
    <details v-for="(file, index) in files" :key="`${file.name}-${index}`" :open="files.length === 1 && structured(file)">
      <summary><FileText :size="16" /><span>{{ file.name }}</span><small>{{ file.text.length.toLocaleString() }} characters</small></summary>
      <div class="uploaded-body"><MarketingDataCard v-if="marketing(file)" :data="structured(file)" :theme="theme" /><ResultTree v-else-if="structured(file)" :value="structured(file)" :theme="theme" /><pre v-else>{{ file.text }}</pre></div>
    </details>
  </section>
</template>
<script setup>
import { FileText } from 'lucide-vue-next'
import ResultTree from './ResultTree.vue'
import MarketingDataCard from './MarketingDataCard.vue'
import { analyzeMarketingData } from '../../workspace/marketingData.js'
import { parseCsv } from '../../workspace/parseCsv.js'
defineProps({ files: { type: Array, default: () => [] }, theme: { default: 'light' } })
function marketing(file) { return !!analyzeMarketingData(structured(file)) }
function structured(file) {
  try {
    if (/\.json$/i.test(file.name)) return JSON.parse(file.text)
    if (/\.csv$/i.test(file.name)) return parseCsv(file.text)
  } catch { /* The source remains readable even when it is not structured data. */ }
  return null
}
</script>
<style scoped>
.uploaded-context{display:grid;gap:8px;margin:12px 0;min-width:0}.uploaded-context details{border:1px solid var(--line);border-radius:12px;background:var(--panel);min-width:0;overflow:hidden}.uploaded-context summary{display:flex;align-items:center;gap:10px;padding:12px 14px;cursor:pointer;font-size:12px}.uploaded-context summary span{overflow-wrap:anywhere;min-width:0}.uploaded-context summary small{margin-left:auto;color:var(--muted);white-space:nowrap;font-size:11px}.uploaded-body{padding:4px 14px 14px;max-height:420px;overflow:auto}.uploaded-body pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:12px;line-height:1.7}@media(max-width:500px){.uploaded-context summary{flex-wrap:wrap}.uploaded-context summary small{margin-left:26px}}
</style>
