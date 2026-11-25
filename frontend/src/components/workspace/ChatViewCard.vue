<template>
  <!-- A workspace view shown inline in the chat: the dashboard map and insight panels, projects, skills, connectors,
       a settings summary and spend. Read-only and free; each links to its full page. -->
  <section class="cvc" :class="`cvc-${spec.view}`" :aria-labelledby="`${uid}-title`">
    <header class="cvc-head">
      <div class="cvc-title">
        <span class="cvc-kicker"><component :is="icon" :size="13" aria-hidden="true" />{{ kicker }}</span>
        <h3 :id="`${uid}-title`">{{ title }}</h3>
      </div>
      <span class="cvc-badges"><span class="cvc-badge free">Free · no model call</span><span v-if="simulated" class="cvc-badge sim">Simulated</span></span>
    </header>

    <div class="cvc-body">
      <LoadingSkeleton v-if="loading" variant="cards" :lines="3" :label="`Loading ${title.toLowerCase()}`" />
      <p v-else-if="error" class="cvc-error" role="alert">{{ error }} <button type="button" class="cvc-link" @click="load">Try again</button></p>

      <template v-else-if="spec.view === 'dashboard_map'">
        <AudienceWorldMap v-if="hasPlaces" :geography="insights.geography" :theme="theme" />
        <p v-else class="cvc-empty">No saved run has people with places yet.</p>
      </template>

      <template v-else-if="spec.view === 'insights'">
        <p v-if="!insights.total_runs" class="cvc-empty">No saved runs yet, so there is nothing to add up. Start a test and it shows here.</p>
        <template v-else-if="spec.panel">
          <component :is="panelComponent" v-bind="panelProps" @select-day="selectDay" @changed="load" />
        </template>
        <template v-else>
          <AudienceWorldMap v-if="hasPlaces" :geography="insights.geography" :theme="theme" />
          <LiveNow :runs="liveRuns" @changed="load" />
          <div class="ovi-grid cvc-grid">
            <ActivityCalendar :activity="insights.activity" :selected="day" @select-day="selectDay" />
            <IntentPanel :intent="insights.intent" />
            <ObjectionsPanel :objections="insights.objections" />
            <AudiencesPanel :segments="insights.segments" />
            <TrustPanel :trust="insights.trust" :forecasts="insights.forecasts" :total-runs="insights.total_runs" />
            <SpendPanel :spend="insights.spend" />
          </div>
        </template>
        <div v-if="dayRuns.length" class="cvc-day" role="group" :aria-label="`Runs saved on ${day}`">
          <span>Saved on {{ day }}:</span>
          <button v-for="r in dayRuns" :key="r.name" type="button" @click="emit('open-run', r.name)">{{ r.title }}</button>
        </div>
      </template>

      <template v-else-if="spec.view === 'projects'">
        <ul v-if="projects.length" class="cvc-list" aria-label="Projects">
          <li v-for="p in projects" :key="p.id">
            <RouterLink :to="{ path: '/', query: { project: p.id } }"><FolderOpen :size="16" aria-hidden="true" /><span><b>{{ p.name }}</b><small>{{ p.description || 'Project instructions and related chats' }}</small><small>{{ p.chat_ids?.length || 0 }} chats · {{ p.run_names?.length || 0 }} runs</small></span><ChevronRight :size="15" aria-hidden="true" /></RouterLink>
          </li>
        </ul>
        <p v-else class="cvc-empty">No projects yet. A project keeps related chats, runs and instructions together.</p>
      </template>

      <template v-else-if="spec.view === 'skills'">
        <details v-for="g in skillGroups" :key="g.group" class="cvc-group" :open="g.group === 'Show in chat'">
          <summary>{{ g.group }} <small>{{ g.items.length }}</small></summary>
          <ul class="cvc-skills">
            <li v-for="item in g.items" :key="item.id">
              <button type="button" @click="emit('feature', item)">
                <span><b>{{ item.label }}</b> <code>{{ item.command }}</code><small>{{ item.description }}</small></span>
                <span class="cvc-cost" :class="item.cost === 'free' ? 'free' : 'asks'">{{ item.cost === 'free' ? 'Free' : 'Asks first' }}</span>
              </button>
            </li>
          </ul>
        </details>
      </template>

      <template v-else-if="spec.view === 'connectors'">
        <h4 class="cvc-sub">Models</h4>
        <ul class="cvc-rows" aria-label="Model providers">
          <li v-for="p in shownProviders" :key="p.id"><span>{{ p.label }}<small v-if="p.id === llm.provider"> · in use: {{ llm.model || 'default model' }}</small></span><b :class="p.on ? 'on' : 'off'">{{ p.on ? 'Key set' : 'No key' }}</b></li>
          <li v-if="hiddenProviders" class="cvc-more-row"><span>{{ hiddenProviders }} other {{ hiddenProviders === 1 ? 'provider has' : 'providers have' }} no key</span></li>
          <li v-if="llm.gateway"><span>Gateway<small> · {{ llm.gateway }}</small></span><b class="on">On</b></li>
        </ul>
        <h4 class="cvc-sub">Connected tools (MCP)</h4>
        <ul v-if="connectors.length" class="cvc-rows" aria-label="Connected tools">
          <li v-for="c in connectors" :key="c.id"><span>{{ c.name || 'Unnamed connector' }}<small>{{ connectorDetail(c) }}</small></span><b :class="c.enabled ? 'on' : 'off'">{{ c.enabled ? 'On' : 'Off' }}</b></li>
        </ul>
        <p v-else class="cvc-empty">No connected tools yet. Add one on the Connections page to bring ads, analytics or CRM data into the chat.</p>
        <p class="cvc-note">A key or a connector being set up does not mean an outside account was checked; test it on the Connections page.</p>
      </template>

      <template v-else-if="spec.view === 'settings_summary'">
        <dl class="cvc-dl">
          <div><dt>Model provider</dt><dd>{{ providerLabel(llm.provider) || 'Not set' }}</dd></div>
          <div><dt>Model</dt><dd>{{ llm.model || 'Default' }}</dd></div>
          <div><dt>API key</dt><dd>{{ llm.api_key_configured ? 'Set' : llm.gateway ? 'Using a gateway' : 'Not set' }}</dd></div>
          <div><dt>Persona memory</dt><dd>{{ memoryLabel }}</dd></div>
          <div><dt>Jev decision engine</dt><dd>{{ settings?.jev?.configured ? 'Set up' : 'Not set up' }}</dd></div>
          <div><dt>Spending limit</dt><dd>{{ spending.process_limit_usd ? `${usd(spending.process_limit_usd)} per server process` : 'No limit set' }}</dd></div>
        </dl>
        <p v-if="settings?.restart_required" class="cvc-note">A saved change waits for a restart of the local server.</p>
        <p v-if="llm.locked" class="cvc-note">{{ llm.locked_reason }}</p>
      </template>

      <template v-else-if="spec.view === 'spend'">
        <ul class="cvc-numbers" aria-label="Model spend since the server started, estimated">
          <li><b>{{ usd(spending.process_spent_usd) }}</b><span>spent since the server started</span><small>estimate</small></li>
          <li><b>{{ Number(spending.process_calls || 0).toLocaleString('en-US') }}</b><span>model calls counted</span></li>
          <li><b>{{ spending.process_limit_usd ? usd(spending.process_limit_usd) : 'None' }}</b><span>spending limit</span></li>
          <li v-if="spending.run_cap"><b>{{ usd(spending.run_cap.spent_usd) }} of {{ usd(spending.run_cap.limit_usd) }}</b><span>running test’s cap{{ spending.run_cap.reached ? ', reached' : '' }}</span></li>
        </ul>
        <SpendPanel v-if="insights.total_runs" :spend="insights.spend" />
        <p class="cvc-note">{{ spending.enforcement || 'Estimated at list prices per call; your provider’s bill is the real figure.' }}</p>
      </template>
    </div>

    <footer class="cvc-actions" aria-label="Open the full page">
      <RouterLink v-if="fullPage" :to="fullPage.to"><ExternalLink :size="15" aria-hidden="true" />{{ fullPage.label }}</RouterLink>
      <button v-if="spec.view === 'connectors'" type="button" @click="emit('panel', 'connectors')"><Plug :size="15" aria-hidden="true" />Manage connections</button>
      <button v-if="['settings_summary', 'spend', 'connectors'].includes(spec.view)" type="button" @click="emit('panel', spec.view === 'spend' ? 'spending' : 'settings')"><Settings2 :size="15" aria-hidden="true" />{{ spec.view === 'spend' ? 'Change the limit in Settings' : 'Open settings' }}</button>
      <button v-if="!loading && spec.view !== 'skills'" type="button" @click="load"><RefreshCw :size="15" aria-hidden="true" />Refresh</button>
    </footer>
  </section>
</template>

<script setup>
// The non-run views of "everything from the chat". Each reads the same endpoint its full page reads, with the user's
// own session, so a view never shows more than that page would. No model calls.
import { computed, defineAsyncComponent, ref, useId, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronRight, ExternalLink, FolderOpen, Globe2, LayoutDashboard, Plug, RefreshCw, Settings2, Shapes, Wallet } from 'lucide-vue-next'
import LoadingSkeleton from './LoadingSkeleton.vue'
import ActivityCalendar from './overview/ActivityCalendar.vue'
import IntentPanel from './overview/IntentPanel.vue'
import ObjectionsPanel from './overview/ObjectionsPanel.vue'
import AudiencesPanel from './overview/AudiencesPanel.vue'
import TrustPanel from './overview/TrustPanel.vue'
import SpendPanel from './overview/SpendPanel.vue'
import LiveNow from './overview/LiveNow.vue'
import { api } from '../../workspace/api.js'
import { namesOnDay, normalizeInsights, pollable, usd } from '../../workspace/overviewInsights.js'
import { featureCatalog } from '../../workspace/featureCatalog.js'
import { CHAT_VIEWS, INSIGHT_PANELS } from '../../workspace/chatViews.js'
const AudienceWorldMap = defineAsyncComponent(() => import('./overview/AudienceWorldMap.vue'))

const props = defineProps({
  spec: { type: Object, required: true },
  runs: { type: Array, default: () => [] },
  theme: { type: String, default: 'light' }
})
const emit = defineEmits(['panel', 'feature', 'open-run'])
const uid = useId()
const loading = ref(false), error = ref('')
const insights = ref(normalizeInsights(null)), projects = ref([]), connectors = ref([]), settings = ref(null)
const day = ref('')

const title = computed(() => (props.spec.view === 'insights' && props.spec.panel ? INSIGHT_PANELS[props.spec.panel] : CHAT_VIEWS[props.spec.view]?.label || 'View'))
const kicker = computed(() => ({ dashboard_map: 'Dashboard', insights: 'Dashboard', projects: 'Workspace', skills: 'Workspace', connectors: 'Connections', settings_summary: 'Settings', spend: 'Spending' }[props.spec.view] || 'Workspace'))
const icon = computed(() => ({ dashboard_map: Globe2, insights: LayoutDashboard, projects: FolderOpen, skills: Shapes, connectors: Plug, settings_summary: Settings2, spend: Wallet }[props.spec.view] || LayoutDashboard))
const simulated = computed(() => !!CHAT_VIEWS[props.spec.view]?.simulated)
const fullPage = computed(() => ({
  dashboard_map: { to: '/workspace', label: 'Open the dashboard' },
  insights: { to: '/workspace', label: 'Open the dashboard' },
  projects: { to: '/workspace/projects', label: 'All projects' },
  skills: { to: '/workspace/skills', label: 'All skills' }
}[props.spec.view] || null))

const needs = computed(() => {
  const v = props.spec.view
  return {
    insights: ['dashboard_map', 'insights', 'spend'].includes(v),
    projects: v === 'projects',
    connectors: v === 'connectors',
    settings: ['connectors', 'settings_summary', 'spend'].includes(v)
  }
})
let ticket = 0
async function load() {
  const mine = ++ticket
  if (props.spec.view === 'skills') return
  loading.value = true; error.value = ''
  try {
    const n = needs.value
    const [ins, proj, conn, set] = await Promise.all([
      n.insights ? api('/api/runs/insights') : null,
      n.projects ? api('/api/workspace/projects') : null,
      n.connectors ? api('/api/workspace/connectors') : null,
      n.settings ? api('/api/workspace/settings') : null
    ])
    if (mine !== ticket) return
    if (n.insights) insights.value = normalizeInsights(ins)
    if (n.projects) projects.value = Array.isArray(proj) ? proj : []
    if (n.connectors) connectors.value = Array.isArray(conn) ? conn : []
    if (n.settings) settings.value = set || null
  } catch (e) {
    if (mine === ticket) error.value = /401|403|forbidden|denied/i.test(e.message || '') ? 'You do not have access to this in this workspace.' : e.message || 'Could not load this view.'
  } finally {
    if (mine === ticket) loading.value = false
  }
}
watch(() => props.spec.view, load, { immediate: true })

const hasPlaces = computed(() => insights.value.geography.countries.length > 0 || insights.value.geography.cities.length > 0)
const liveRuns = computed(() => pollable(insights.value.running))
const panelComponent = computed(() => ({ activity_calendar: ActivityCalendar, intent: IntentPanel, objections: ObjectionsPanel, audiences: AudiencesPanel, trust: TrustPanel, spend: SpendPanel, live_runs: LiveNow }[props.spec.panel]))
const panelProps = computed(() => {
  const i = insights.value
  return {
    activity_calendar: { activity: i.activity, selected: day.value }, intent: { intent: i.intent }, objections: { objections: i.objections },
    audiences: { segments: i.segments }, trust: { trust: i.trust, forecasts: i.forecasts, totalRuns: i.total_runs }, spend: { spend: i.spend }, live_runs: { runs: liveRuns.value }
  }[props.spec.panel] || {}
})
function selectDay(value) { day.value = value || '' }
const dayRuns = computed(() => {
  if (!day.value) return []
  const names = namesOnDay(insights.value.activity, day.value)
  return [...names].map((name) => ({ name, title: props.runs.find((r) => r.name === name)?.title || name }))
})

const skillGroups = computed(() => {
  const groups = new Map()
  for (const item of featureCatalog) {
    if (!groups.has(item.group)) groups.set(item.group, [])
    groups.get(item.group).push(item)
  }
  return [...groups].map(([group, items]) => ({ group, items }))
})

const llm = computed(() => settings.value?.llm || {})
const spending = computed(() => settings.value?.spending || {})
const PROVIDER_LABELS = { claude: 'Anthropic', openai: 'OpenAI', gemini: 'Google Gemini', ollama: 'Ollama' }
const providerLabel = (id) => (llm.value.providers || []).find((p) => p.id === id)?.label || PROVIDER_LABELS[id] || id || ''
const providers = computed(() => (llm.value.providers || []).map((p) => ({ id: p.id, label: p.label || providerLabel(p.id), on: !!p.key_configured })))
// the providers that matter: the one in use and any with a key; the rest are counted, not listed
const shownProviders = computed(() => providers.value.filter((p) => p.on || p.id === llm.value.provider))
const hiddenProviders = computed(() => providers.value.length - shownProviders.value.length)
const memoryLabel = computed(() => {
  const m = settings.value?.memory || {}
  return (m.providers || []).find((p) => p.id === m.backend)?.label || m.backend || 'Local memory'
})
function connectorDetail(c) {
  const tools = Array.isArray(c.tools) ? c.tools.length : 0
  const status = { ok: 'checked', not_tested: 'not checked yet', error: 'last check failed' }[c.status] || String(c.status || '').replaceAll('_', ' ')
  return [status && ` · ${status}`, tools ? ` · ${tools} tools` : ''].join('')
}
</script>

<style scoped>
.cvc { margin-top: 14px; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); min-width: 0; overflow: hidden; box-shadow: 0 1px 2px rgb(20 20 40 / 3%); }
.cvc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 16px 18px 0; }
.cvc-title { min-width: 0; }
.cvc-kicker { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 550; color: var(--muted); }
.cvc-title h3 { margin: 4px 0 0; font-size: 15px; font-weight: 600; line-height: 1.4; overflow-wrap: anywhere; }
.cvc-badges { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; flex-shrink: 0; }
.cvc-badge { font-size: 10.5px; font-weight: 600; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--line); line-height: 1.8; white-space: nowrap; color: var(--muted); }
.cvc-badge.free { color: var(--yes); border-color: color-mix(in srgb, var(--yes) 45%, var(--line)); }
.cvc-badge.sim { color: var(--warm); border-color: color-mix(in srgb, var(--warm) 45%, var(--line)); }
.cvc-body { padding: 14px 18px 4px; min-width: 0; max-height: 720px; overflow: auto; overscroll-behavior: contain; }
.cvc-body :deep(.awm), .cvc-body :deep(.ovi-panel) { margin: 0 0 12px; }
.cvc-grid { margin: 0; }
.cvc-empty { margin: 0 0 12px; padding: 18px; border: 1px dashed var(--line); border-radius: 12px; color: var(--muted); font-size: 12.5px; line-height: 1.6; text-align: center; }
.cvc-error { margin: 0 0 12px; font-size: 12.5px; }
.cvc-link { padding: 0; border: 0; background: none; color: var(--accent); font: inherit; font-size: 12.5px; font-weight: 550; cursor: pointer; }
.cvc-note { margin: 10px 0 12px; font-size: 11px; line-height: 1.6; color: var(--muted); }
.cvc-sub { margin: 4px 0 8px; font-size: 12px; font-weight: 600; color: var(--muted); }
.cvc-list, .cvc-rows, .cvc-skills { list-style: none; margin: 0 0 12px; padding: 0; display: grid; gap: 6px; }
.cvc-list a { display: flex; align-items: center; gap: 12px; min-height: 44px; padding: 11px 13px; border: 1px solid var(--line); border-radius: 12px; color: var(--text); text-decoration: none; }
.cvc-list a:hover { background: var(--panel-2); }
.cvc-list a > svg:first-child { color: var(--accent); flex-shrink: 0; }
.cvc-list a > svg:last-child { margin-left: auto; color: var(--muted); flex-shrink: 0; }
.cvc-list span { min-width: 0; display: grid; gap: 2px; }
.cvc-list b { font-size: 13px; font-weight: 550; overflow-wrap: anywhere; }
.cvc-list small { font-size: 11.5px; color: var(--muted); overflow-wrap: anywhere; }
.cvc-rows li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 12px; border: 1px solid var(--line); border-radius: 10px; font-size: 12.5px; min-width: 0; }
.cvc-rows li > span { min-width: 0; overflow-wrap: anywhere; }
.cvc-rows small { color: var(--muted); }
.cvc-rows b { flex-shrink: 0; font-size: 11px; font-weight: 600; padding: 0 8px; border-radius: 999px; border: 1px solid var(--line); line-height: 1.8; }
.cvc-rows b.on { color: var(--yes); border-color: color-mix(in srgb, var(--yes) 45%, var(--line)); }
.cvc-rows b.off { color: var(--muted); }
.cvc-rows li.cvc-more-row { border-style: dashed; color: var(--muted); }
.cvc-dl { margin: 0 0 8px; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }
.cvc-dl div { padding: 10px 12px; border-radius: 11px; background: var(--panel-2); min-width: 0; }
.cvc-dl dt { font-size: 11px; color: var(--muted); }
.cvc-dl dd { margin: 2px 0 0; font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.cvc-numbers { list-style: none; margin: 0 0 12px; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
.cvc-numbers li { display: grid; gap: 1px; padding: 9px 12px; border-radius: 11px; background: var(--panel-2); min-width: 0; }
.cvc-numbers b { font-size: 16px; font-weight: 650; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.cvc-numbers span { font-size: 12px; }
.cvc-numbers small { font-size: 10.5px; color: var(--warm); }
.cvc-group { margin: 0 0 8px; border: 1px solid var(--line); border-radius: 12px; }
.cvc-group > summary { display: flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 14px; font-size: 13px; font-weight: 600; cursor: pointer; }
.cvc-group > summary small { color: var(--muted); font-weight: 400; }
.cvc-skills { padding: 0 8px 8px; margin: 0; }
.cvc-skills button { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; min-height: 44px; padding: 8px 10px; border: 0; border-radius: 9px; background: transparent; color: var(--text); font: inherit; text-align: left; cursor: pointer; }
.cvc-skills button:hover, .cvc-skills button:focus-visible { background: var(--panel-2); }
.cvc-skills button > span:first-child { min-width: 0; display: grid; gap: 2px; }
.cvc-skills b { font-size: 12.5px; font-weight: 550; }
.cvc-skills code { font-size: 11px; color: var(--muted); }
.cvc-skills small { font-size: 11px; color: var(--muted); line-height: 1.45; }
.cvc-cost { flex-shrink: 0; font-size: 10.5px; font-weight: 600; padding: 0 8px; border-radius: 999px; border: 1px solid var(--line); line-height: 1.8; white-space: nowrap; }
.cvc-cost.free { color: var(--yes); border-color: color-mix(in srgb, var(--yes) 45%, var(--line)); }
.cvc-cost.asks { color: var(--warm); border-color: color-mix(in srgb, var(--warm) 45%, var(--line)); }
.cvc-day { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 12px; font-size: 12px; color: var(--muted); }
.cvc-day button { min-height: 32px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--text); font: inherit; font-size: 12px; cursor: pointer; }
.cvc-actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 18px 14px; border-top: 1px solid var(--line); }
.cvc-actions > a, .cvc-actions > button { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 6px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; font-weight: 500; text-decoration: none; cursor: pointer; }
.cvc-actions > a:hover, .cvc-actions > button:hover { background: var(--panel-2); }
.cvc-actions svg { color: var(--muted); flex-shrink: 0; }
@media (max-width: 600px) {
  .cvc-head { flex-direction: column; gap: 8px; padding: 14px 14px 0; }
  .cvc-badges { justify-content: flex-start; }
  .cvc-body { padding: 12px 14px 4px; max-height: none; }
  .cvc-actions { padding: 12px 14px 14px; display: grid; grid-template-columns: minmax(0, 1fr); }
  .cvc-actions > a, .cvc-actions > button { min-height: 44px; justify-content: center; }
  .cvc-body :deep(.ovi-grid) { grid-template-columns: minmax(0, 1fr); }
}
</style>
