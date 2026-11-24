<template>
  <div class="result-tree">
    <template v-if="scalar"><span class="result-value">{{ value === null ? 'Not recorded' : String(value) }}</span></template>
    <template v-else-if="rows">
      <label v-if="metrics.length" class="result-metric">Visualize metric
        <select v-model="metric"><option v-for="key in metrics" :key="key" :value="key">{{ label(key) }}</option></select>
      </label>
      <EChart v-if="metric && rows.length" :option="chart" :height="Math.min(500, 90 + pageRows.length * 27)" :label="label(metric)" :theme="theme" />
      <p v-if="metric && rows.length" class="result-chart-note">{{ label(metric) }} for {{ page * size + 1 }}–{{ Math.min(rows.length, (page + 1) * size) }} of {{ rows.length }} recorded rows. Values use the source report’s units.</p>
      <details class="result-recorded-data" :open="!metrics.length"><summary>View recorded rows ({{ rows.length }})</summary><div class="result-table" tabindex="0" role="region" aria-label="Scrollable result table"><table><thead><tr><th v-for="key in columns" :key="key">{{ label(key) }}</th></tr></thead>
        <tbody><tr v-for="(row, i) in pageRows" :key="i"><td v-for="key in columns" :key="key"><ResultTree v-if="row[key] !== null && typeof row[key] === 'object'" :value="row[key]" :theme="theme" :depth="depth + 1" /><span v-else>{{ row[key] ?? 'Not recorded' }}</span></td></tr></tbody>
      </table></div></details>
      <div v-if="rows.length > size" class="result-pages"><button class="ws-btn" :disabled="page === 0" @click="page--">Previous</button><span>{{ page * size + 1 }}–{{ Math.min(rows.length, (page + 1) * size) }} of {{ rows.length }}</span><button class="ws-btn" :disabled="(page + 1) * size >= rows.length" @click="page++">Next</button></div>
    </template>
    <template v-else>
      <div v-if="numberEntries.length" class="result-metrics"><article v-for="([key,item]) in numberEntries" :key="key"><span>{{ label(key) }}</span><strong :title="String(item)">{{ formatNumber(item) }}</strong></article></div>
      <div v-if="textEntries.length" class="result-narrative"><article v-for="([key,item]) in textEntries" :key="key"><h5>{{ Array.isArray(value) ? Number(key) + 1 : label(key) }}</h5><p>{{ item === null || item === '' ? 'Not recorded' : typeof item === 'boolean' ? item ? 'Yes' : 'No' : item }}</p></article></div>
      <details v-for="([key,item], index) in nestedEntries" :key="key" :open="openSection(key,index)"><summary>{{ Array.isArray(value) ? Number(key) + 1 : label(key) }}<small>{{ Array.isArray(item) ? item.length + ' recorded entries' : '' }}</small></summary><ResultTree :value="item" :theme="theme" :depth="depth + 1" /></details>
      <details v-if="technicalEntries.length" class="result-technical"><summary>Technical details</summary><dl><template v-for="([key,item]) in technicalEntries" :key="key"><dt>{{ label(key) }}</dt><dd><ResultTree v-if="!isSimple(item)" :value="item" :theme="theme" :depth="depth + 1" /><span v-else>{{ item }}</span></dd></template></dl></details>
      <p v-if="!Object.keys(value || {}).length" class="ws-note">No entries recorded.</p>
    </template>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import EChart from './EChart.vue'
import { palette } from '../../workspace/charts.js'
import { readableLabel, tableRows, technicalKey } from '../../workspace/reportPresentation'
const props = defineProps({ value: { default: null }, theme: { default: 'light' }, depth: { type: Number, default: 0 } })
const fieldLabels = { n: 'Recorded count', people: 'Simulated participants', agents: 'Participant count', convert_yes: 'Would convert: yes', convert_maybe: 'Would convert: maybe', convert_no: 'Would convert: no', by_segment: 'Results by audience segment', by_country: 'Results by country', by_community: 'Results by community', by_age: 'Results by age', marketing: 'Audience findings', decision: 'Saved decision', persona_index: 'Persona profiles', funnel: 'Buyer funnel', pricing: 'Pricing reactions' }
const label = key => fieldLabels[key] || readableLabel(key)
const isSimple = (x) => x === null || typeof x !== 'object'
const scalar = computed(() => isSimple(props.value))
const entries = computed(() => Object.entries(props.value || {}))
const technical = key => technicalKey(key)
const technicalEntries = computed(() => entries.value.filter(([key]) => technical(key)))
const numberEntries = computed(() => entries.value.filter(([key,item]) => !technical(key) && typeof item === 'number' && Number.isFinite(item)))
const textEntries = computed(() => entries.value.filter(([key,item]) => !technical(key) && isSimple(item) && typeof item !== 'number'))
const nestedEntries = computed(() => entries.value.filter(([key,item]) => !technical(key) && !isSimple(item)))
const formatNumber = value => new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 }).format(value)
const openSection = (key,index) => props.depth < 2 && /^(decision|marketing|summary|funnel|pricing|by_segment)$/.test(key) || props.depth === 0 && index === 0 && nestedEntries.value.length <= 4
const rows = computed(() => tableRows(props.value))
const columns = computed(() => [...new Set((rows.value || []).flatMap(Object.keys))])
const metrics = computed(() => columns.value.filter((key) => !/(^id$|_id$)/.test(key) && rows.value.some((r) => Number.isFinite(r[key])) && rows.value.every((r) => r[key] == null || Number.isFinite(r[key]))))
const metric = ref(''), page = ref(0), size = 20
watch(() => props.value, () => { page.value = 0; metric.value = ['convert_yes','yes','count','n','total_actions','conversions','clicks','spend','revenue'].find(key => metrics.value.includes(key)) || metrics.value[0] || '' }, { immediate: true })
const pageRows = computed(() => (rows.value || []).slice(page.value * size, (page.value + 1) * size))
const chart = computed(() => {
  props.theme
  const p = palette(), data = pageRows.value
  const name = ['name', 'segment', 'label', 'key', 'country', 'creative_id', 'agent_name', 'round_num'].find(key => columns.value.includes(key))
  return { tooltip: { trigger: 'axis', confine: true }, grid: { left: 12, right: 30, top: 20, bottom: 20, containLabel: true }, xAxis: { type: 'value', axisLabel: { color: p.muted }, splitLine: { lineStyle: { color: p.line } } }, yAxis: { type: 'category', data: data.map((r, i) => String(r[name] ?? page.value * size + i + 1)).reverse(), axisLabel: { color: p.text, width: 150, overflow: 'truncate' } }, series: [{ type: 'bar', name: label(metric.value), data: data.map((r) => r[metric.value] ?? null).reverse(), itemStyle: { color: p.accent, borderRadius: [0, 3, 3, 0] }, barMaxWidth: 18 }] }
})
</script>
<style scoped>
.result-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:10px;margin:6px 0 18px}.result-metrics article{padding:13px;border:1px solid var(--line);border-radius:11px;background:var(--panel-2);min-width:0}.result-metrics article>span{display:block;color:var(--muted);font-size:10px;line-height:1.6;margin-bottom:7px}.result-metrics strong{font-size:20px;font-weight:550;line-height:1.4;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.result-narrative{display:grid;gap:15px;margin:7px 0 17px}.result-narrative h5{font-size:11px;font-weight:550;color:var(--muted);margin:0 0 5px}.result-narrative p{font-size:13px;line-height:1.8;white-space:pre-wrap;margin:0}.result-recorded-data{margin-top:14px}.result-chart-note{font-size:10px;line-height:1.7;color:var(--muted);margin:0 0 10px}.result-technical{color:var(--muted);font-size:11px;margin-top:12px}.result-technical dl{display:grid;grid-template-columns:minmax(80px,1fr) 2fr;gap:9px;margin:12px 0}.result-technical dd{margin:0;overflow-wrap:anywhere}.result-technical dt{font-weight:500}
.result-tree {font-size:13px;line-height:1.65;min-width:0;overflow-wrap:anywhere}.result-tree details {border-bottom:1px solid var(--line);padding:7px 0}.result-tree details > .result-tree {padding:8px 0 8px 14px}.result-tree summary {cursor:pointer;font-weight:550}.result-tree summary small {margin-left:10px;color:var(--muted);font-weight:400}.result-value {white-space:pre-wrap}.result-table {overflow:auto;max-height:520px}.result-table table {border-collapse:collapse;min-width:100%;text-align:left}.result-table td,.result-table th {border-bottom:1px solid var(--line);padding:9px 12px;min-width:110px;max-width:400px;vertical-align:top}.result-table th {background:var(--panel-2);position:sticky;top:0;white-space:nowrap}.result-pages {display:flex;align-items:center;justify-content:space-between;gap:10px;padding-top:12px;color:var(--muted)}.result-metric {display:flex;gap:10px;align-items:center;color:var(--muted);margin-bottom:10px}.result-metric select {border:1px solid var(--line);border-radius:6px;padding:5px;background:var(--panel);color:var(--text)}
</style>
