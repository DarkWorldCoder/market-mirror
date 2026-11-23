<template>
  <section class="chat-artifact" :aria-label="title || file">
    <header><div><b>{{ title || reportInfo(file).title }}</b></div><button class="ws-btn" @click="save">Download</button></header>
    <p v-if="loading" class="ws-note">Loading saved results…</p>
    <p v-else-if="error" class="ws-error" role="alert">{{ error }} <button class="ws-btn" @click="load">Retry</button></p>
    <template v-else-if="file.endsWith('.html')"><p class="ws-note">Saved interactive dashboard</p><button class="ws-btn" @click="openSaved">Open dashboard</button></template>
    <div v-else class="chat-artifact-content" role="region" tabindex="0" :aria-label="`${title || file} saved content`">
      <ResultTree v-if="file.endsWith('.json') || file.endsWith('.csv')" :value="content" :theme="theme" />
      <pre v-else>{{ content }}</pre>
    </div>
    <details class="artifact-source"><summary>Source details</summary><p>{{ name }} / {{ file }}{{ path.length ? ` / ${path.join(' / ')}` : '' }}</p></details>
  </section>
</template>
<script setup>
import { ref, watch } from 'vue'
import ResultTree from './ResultTree.vue'
import { reportInfo } from '../../workspace/reportPresentation'
import { api, download, openHtml } from '../../workspace/api.js'
import { parseCsv } from '../../workspace/parseCsv.js'
import { funnelRows } from '../../workspace/resultRouting.js'
const props = defineProps({ name: { type: String, required: true }, file: { type: String, required: true }, path: { type: Array, default: () => [] }, title: { type: String, default: '' }, files: { type: Array, default: () => [] }, theme: { type: String, default: 'light' } })
const content = ref(null), loading = ref(false), error = ref('')
let request = 0
async function load() {
  const ticket = ++request; loading.value = true; error.value = ''
  try {
    if (!props.files.includes(props.file)) throw new Error('This report is no longer present in the saved run.')
    let data = props.file.endsWith('.html') ? null : await api(`/api/runs/${encodeURIComponent(props.name)}/files/${encodeURIComponent(props.file)}`)
    for (const key of props.path) { if (!data || !Object.hasOwn(data, key)) throw new Error('This saved report section is unavailable.'); data = data[key] }
    if (props.path.at(-1) === 'funnel') data = funnelRows(data)
    if (props.file.endsWith('.csv')) data = parseCsv(data)
    if (ticket === request) content.value = data
  } catch (e) { if (ticket === request) error.value = e.message }
  finally { if (ticket === request) loading.value = false }
}
watch(() => [props.name, props.file, props.path], load, { immediate: true })
async function save() { try { await download(props.name, props.file) } catch (e) { error.value = e.message } }
async function openSaved() { try { await openHtml(props.name, props.file) } catch (e) { error.value = e.message } }
</script>
<style scoped>
.artifact-source{margin-top:12px;font-size:11px;color:var(--muted)}.artifact-source summary{cursor:pointer}.artifact-source p{margin-top:6px;overflow-wrap:anywhere}.chat-artifact{margin-top:14px;border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:16px;min-width:0}.chat-artifact header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}.chat-artifact header b{display:block;font-size:14px}.chat-artifact header small{display:block;margin-top:5px;font-size:11px;color:var(--muted);overflow-wrap:anywhere}.chat-artifact-content{max-height:620px;overflow:auto;min-width:0}.chat-artifact pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:13px;line-height:1.8}
</style>
