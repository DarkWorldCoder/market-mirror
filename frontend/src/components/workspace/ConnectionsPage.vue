<template>
  <div class="mm-conn-page">
    <div class="ws-catalog-head">
      <div><h1>Connections</h1><p class="ws-note">Bring your data and tools into MarketMirror, and use MarketMirror from your other AI apps.</p></div>
    </div>
    <ul class="mm-conn-summary" aria-label="Connection summary">
      <li><span><Plug :size="15" aria-hidden="true" /><b>{{ summary.connected }}</b> of {{ summary.servers }} MCP {{ summary.servers === 1 ? 'server' : 'servers' }} connected<template v-if="summary.failing">, {{ summary.failing }} need attention</template></span></li>
      <li><span><Wrench :size="15" aria-hidden="true" /><b>{{ summary.toolsOn }}</b> {{ summary.toolsOn === 1 ? 'tool' : 'tools' }} on in chat</span></li>
      <li><button type="button" @click="settingsOpen = true"><Cpu :size="15" aria-hidden="true" /><b>{{ summary.modelsReady }}</b> {{ summary.modelsReady === 1 ? 'model' : 'models' }} ready · Model settings</button></li>
    </ul>
    <div class="mm-conn-tabs workspace-modal-tabs" role="tablist" aria-label="Connection type" @keydown="keys">
      <button v-for="t in tabs" :id="`${uid}-${t.id}`" :key="t.id" type="button" role="tab" :aria-selected="tab === t.id" :aria-controls="`${uid}-panel`" :tabindex="tab === t.id ? 0 : -1" @click="select(t.id)"><component :is="t.icon" aria-hidden="true" />{{ t.label }}</button>
    </div>
    <section :id="`${uid}-panel`" role="tabpanel" :aria-labelledby="`${uid}-${tab}`">
      <template v-if="tab === 'servers'">
        <McpServers ref="servers" :theme="theme" @changed="loadSummary" />
        <p class="mm-note">Chat can use the read-only tools you switch on here: pick them under <b>Tools</b> in the chat box. The default chat assistant does not call these tools yet; the other answer modes do.</p>
      </template>
      <template v-else-if="tab === 'data'">
        <div class="mm-conn-section-head"><div><h2>Data you can bring in</h2><p>Add an export to a chat as evidence, or connect the live account through an MCP server.</p></div></div>
        <div class="mm-conn-grid">
          <article class="mm-conn-card">
            <div class="mm-conn-card-top"><span class="mm-conn-icon"><FolderOpen aria-hidden="true" /></span><div class="mm-conn-body"><div class="mm-conn-title"><h3>Saved experiments</h3><span class="mm-badge" :class="runs.length ? 'ok' : 'idle'">{{ runs.length ? `${runs.length} saved` : 'None yet' }}</span></div><p class="mm-conn-meta">Reports, buyer answers and activity from your earlier runs.</p></div></div>
            <div class="mm-conn-actions"><Button variant="outline" size="sm" as-child><RouterLink to="/workspace/reports">Open reports</RouterLink></Button></div>
          </article>
          <article v-for="s in sources" :key="s.name" class="mm-conn-card">
            <div class="mm-conn-card-top"><span class="mm-conn-icon"><BrandIcon v-if="s.brand" :brand="s.brand" :size="20" /><component :is="s.icon" v-else aria-hidden="true" /></span><div class="mm-conn-body"><div class="mm-conn-title"><h3>{{ s.name }}</h3><span class="mm-badge" :class="sourceStatus(s).tone">{{ sourceStatus(s).label }}</span></div><p class="mm-conn-meta">{{ s.description }}</p><p class="mm-conn-meta">Files: {{ s.files }}</p></div></div>
            <div class="mm-conn-actions"><Button variant="outline" size="sm" @click="attach"><Upload />Add a file in chat</Button><Button v-if="s.preset" variant="ghost" size="sm" @click="connectPreset(s.preset)"><Plug />{{ sourceStatus(s).connector ? 'Manage server' : 'Connect live' }}</Button></div>
          </article>
        </div>
        <p class="mm-note">Files are read as context for that chat. A listed account is not connected until its MCP server shows Connected.</p>
      </template>
      <McpClientSetup v-else />
    </section>
    <WorkspaceSettings v-model:open="settingsOpen" initial-tab="models" :theme="theme" @saved="loadSummary" />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { AppWindow, ChartNoAxesCombined, ContactRound, Cpu, Database, FileText, FolderOpen, Megaphone, MousePointerClick, Plug, Upload, Wrench } from 'lucide-vue-next'
import { Button } from '../ui/button'
import BrandIcon from '../BrandIcon.vue'
import McpServers from './McpServers.vue'
import McpClientSetup from './McpClientSetup.vue'
import WorkspaceSettings from './WorkspaceSettings.vue'
import { api } from '../../workspace/api.js'
import { connectionsSummary, connectorStatus } from '../../workspace/connections.js'

defineProps({ theme: { type: String, default: 'light' }, runs: { type: Array, default: () => [] } })
const route = useRoute(), router = useRouter(), uid = useId()
const tabs = [{ id: 'servers', label: 'MCP servers', icon: Plug }, { id: 'data', label: 'Data imports', icon: Database }, { id: 'apps', label: 'Use in your AI apps', icon: AppWindow }]
const tab = ref(tabs.some(t => t.id === route.query.tab) ? route.query.tab : 'servers')
const servers = ref(null), settingsOpen = ref(false), connectors = ref([]), models = ref([])
const summary = computed(() => connectionsSummary(connectors.value, models.value))
const sources = [
  { name: 'Google Analytics', brand: 'googleanalytics', icon: ChartNoAxesCombined, preset: 'Google Analytics', match: c => /analytics/i.test(c.name), files: 'GA4 CSV or JSON exports', description: 'Traffic, where visitors come from and what converts.' },
  { name: 'Meta Ads', brand: 'meta', icon: Megaphone, preset: 'Meta Ads', match: c => c.url.startsWith('https://mcp.facebook.com/'), files: 'Ads Manager CSV exports', description: 'Ad creative, audiences, spend and results.' },
  { name: 'Google Ads', brand: 'googleads', icon: MousePointerClick, files: 'campaign or search terms CSV', description: 'Campaign spend, clicks, conversions and search terms.' },
  { name: 'PostHog and product analytics', brand: 'posthog', icon: Database, files: 'HogQL, persons or events exports', description: 'Product events, funnels and retention.' },
  { name: 'Product documents', icon: FileText, files: 'PDF, Markdown or text', description: 'A product brief, research notes or a pitch.' },
  { name: 'Customer feedback', icon: ContactRound, files: 'reviews, survey CSV or interview notes', description: 'What real customers said, to ground the simulated people.' }
]
function sourceStatus(s) {
  const connector = s.match && connectors.value.find(s.match)
  if (connector) { const st = connectorStatus(connector); return { connector, tone: st.tone, label: st.tone === 'ok' ? 'Live account connected' : `MCP server: ${st.label.toLowerCase()}` } }
  return { connector: null, tone: 'idle', label: 'Import a file' }
}
async function loadSummary() {
  const [c, m] = await Promise.allSettled([api('/api/workspace/connectors'), api('/api/workspace/models')])
  if (c.status === 'fulfilled') connectors.value = c.value
  if (m.status === 'fulfilled') models.value = m.value.models || []
}
function select(id) { tab.value = id; router.replace({ query: { ...route.query, tab: id === 'servers' ? undefined : id } }) }
function keys(event) {
  const ids = tabs.map(t => t.id), current = ids.indexOf(tab.value)
  const next = event.key === 'ArrowRight' ? (current + 1) % ids.length : event.key === 'ArrowLeft' ? (current + ids.length - 1) % ids.length : event.key === 'Home' ? 0 : event.key === 'End' ? ids.length - 1 : -1
  if (next < 0) return
  event.preventDefault(); select(ids[next]); nextTick(() => document.getElementById(`${uid}-${ids[next]}`)?.focus())
}
async function connectPreset(name) {
  select('servers'); await nextTick()
  const existing = connectors.value.find(sources.find(s => s.preset === name).match)
  if (!existing) servers.value?.openAdd(name)
}
function attach() { router.push({ path: '/', query: { attach: '1' } }) }
watch(() => route.query.tab, value => { if (tabs.some(t => t.id === value)) tab.value = value; else if (!value) tab.value = 'servers' })
// On a phone the tab row scrolls sideways: keep the chosen tab in view.
watch(tab, value => nextTick(() => document.getElementById(`${uid}-${value}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })))
onMounted(() => document.getElementById(`${uid}-${tab.value}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' }))
loadSummary()
</script>
