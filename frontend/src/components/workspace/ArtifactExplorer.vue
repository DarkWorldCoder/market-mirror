<template>
  <section class="artifact-explorer" aria-label="Saved reports">
    <div class="artifact-heading"><h3>Explore the complete research</h3><p>Choose a report to see its findings, charts, and recorded evidence.</p></div>
    <label class="artifact-search"><Search :size="15" /><input v-model="search" type="search" placeholder="Find audience, pricing, research, usage…" aria-label="Find a saved report" /></label>
    <nav v-if="!search" class="artifact-categories workspace-modal-tabs" aria-label="Report categories"><button v-for="group in categories" :key="group" :aria-pressed="category === group" @click="chooseCategory(group)">{{ group }}</button></nav>
    <div class="artifact-reports" role="group" aria-label="Available reports"><button v-for="report in filtered" :key="report.file" :aria-pressed="selected === report.file" @click="select(report.file)"><FileChartColumn :size="16" /><span>{{ report.title }}</span></button><p v-if="!filtered.length" class="ws-note">No matching reports. Search the advanced source files below for technical records.</p></div>
    <article class="artifact-content" aria-live="polite">
      <header v-if="selected" class="artifact-toolbar"><h4>{{ selectedInfo.title }}</h4><p>Saved findings and recorded values from this experiment.</p></header>
      <p v-if="error" class="ws-error" role="alert">{{ error }}<button class="ws-btn" @click="select(selected)">Retry</button></p>
      <p v-else-if="loading" class="ws-note" role="status">Opening {{ selectedInfo.title.toLowerCase() }}…</p>
      <template v-else-if="selected"><ResultTree v-if="/\.(json|csv)$/i.test(selected)" :key="selected" :value="content" :theme="theme" /><MarkdownText v-else-if="selected.endsWith('.md')" :text="String(content || '')" /><pre v-else-if="!selected.endsWith('.html')" class="artifact-text">{{ content }}</pre><div v-else><p class="ws-note">Open the original interactive dashboard in a separate tab.</p><button class="ws-btn" @click="openSaved">Open saved dashboard<ArrowUpRight :size="14" /></button></div></template>
      <p v-else class="ws-note">No reports were saved in this run.</p>
    </article>
    <details class="artifact-advanced"><summary>Advanced: source files & downloads</summary><p class="ws-note">All {{ files.length }} original files remain available. Select a source to inspect it or download the selected file.</p><div class="artifact-source-list"><button v-for="file in sourceFiles" :key="file" :aria-pressed="selected === file" @click="select(file)">{{ file }}</button></div><div v-if="selected" class="artifact-download"><code>{{ selected }}</code><button class="ws-btn" @click="save"><Download :size="14" />Download original</button></div></details>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { FileChartColumn, Download, Search, ArrowUpRight } from 'lucide-vue-next'
import ResultTree from './ResultTree.vue'
import MarkdownText from './MarkdownText.vue'
import { parseCsv } from '../../workspace/parseCsv.js'
import { api, download, openHtml } from '../../workspace/api.js'
import { reportInfo, preferredReport } from '../../workspace/reportPresentation'
const props = defineProps({ name: { type: String, required: true }, files: { type: Array, default: () => [] }, theme: { default: 'light' } })
const search = ref(''), selected = ref(''), category = ref('Results'), content = ref(null), loading = ref(false), error = ref('')
let request = 0, currentName = ''
const reports = computed(() => props.files.map(reportInfo))
const categories = computed(() => [...new Set(reports.value.filter(report => report.category !== 'Advanced').map(report => report.category))])
const selectedInfo = computed(() => reportInfo(selected.value))
const filtered = computed(() => reports.value.filter(report => report.category !== 'Advanced' && (search.value ? `${report.title} ${report.file}`.toLowerCase().includes(search.value.toLowerCase()) : report.category === category.value)))
const sourceFiles = computed(() => props.files.filter(file => !search.value || `${file} ${reportInfo(file).title}`.toLowerCase().includes(search.value.toLowerCase())))
function chooseCategory(group) { category.value = group; const file = reports.value.find(report => report.category === group)?.file; if (file) select(file) }
watch(() => [props.name, props.files], () => { if (currentName !== props.name || !props.files.includes(selected.value)) { currentName = props.name; const file = preferredReport(props.files); category.value = reportInfo(file).category; if (file) select(file); else { request++; selected.value = ''; content.value = null } } }, { immediate: true })
async function select(file) {
 const ticket = ++request; selected.value = file; error.value = ''; content.value = null; loading.value = true
 try { const data = file.endsWith('.html') ? null : await api(`/api/runs/${encodeURIComponent(props.name)}/files/${encodeURIComponent(file)}`); if (ticket === request) content.value = file.endsWith('.csv') ? parseCsv(String(data)) : data }
 catch (err) { if (ticket === request) error.value = err.message }
 finally { if (ticket === request) loading.value = false }
}
async function save() { try { await download(props.name, selected.value) } catch (err) { error.value = err.message } }
async function openSaved() { try { await openHtml(props.name, selected.value) } catch (err) { error.value = err.message } }
</script>
<style scoped>
.artifact-explorer{margin-top:28px;padding-top:25px;border-top:1px solid var(--line)}.artifact-heading h3{font-size:17px;font-weight:550;margin-bottom:7px}.artifact-heading p,.artifact-toolbar p{font-size:12px;color:var(--muted);line-height:1.7}.artifact-search{display:flex;align-items:center;gap:9px;margin:18px 0;padding:0 12px;border:1px solid var(--line);border-radius:10px;color:var(--muted);background:var(--panel)}.artifact-search input{width:100%;padding:11px 0;border:0;background:none;color:var(--text);font:inherit;font-size:12px;outline:none}.artifact-search:focus-within{outline:2px solid var(--accent);outline-offset:2px}.artifact-categories{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}.artifact-categories button{padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--muted);font-size:11px;cursor:pointer}.artifact-categories button[aria-pressed=true]{background:var(--accent-2);border-color:var(--accent);color:var(--text)}.artifact-reports{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:18px}.artifact-reports button{display:flex;align-items:center;gap:7px;padding:9px 11px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--muted);font-size:11px;text-align:left;cursor:pointer}.artifact-reports button[aria-pressed=true]{color:var(--text);border-color:var(--accent);background:var(--panel-2)}.artifact-content{min-width:0;padding:20px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}.artifact-toolbar{margin-bottom:19px;padding-bottom:15px;border-bottom:1px solid var(--line)}.artifact-toolbar h4{font-size:15px;font-weight:550;margin:0 0 5px}.artifact-text{font-family:inherit;font-size:13px;line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere}.artifact-advanced{margin-top:17px;padding:14px 0;color:var(--muted);font-size:11px}.artifact-advanced>summary{cursor:pointer;font-size:12px}.artifact-advanced>.ws-note{margin:12px 0}.artifact-source-list{display:flex;flex-wrap:wrap;gap:6px}.artifact-source-list button{padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--muted);font:inherit;font-family:monospace;cursor:pointer}.artifact-source-list button[aria-pressed=true]{color:var(--text);border-color:var(--accent)}.artifact-download{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:15px}.artifact-download code{font-size:10px;overflow-wrap:anywhere}.ws-btn{display:inline-flex;align-items:center;gap:6px}@media(max-width:600px){.artifact-content{padding:15px}.artifact-download{align-items:flex-start;flex-direction:column}}
</style>
