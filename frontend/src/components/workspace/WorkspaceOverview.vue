<template>
  <div class="overview">
    <header class="overview-heading">
      <div>
        <h1>{{ mode === 'reports' ? 'Your experiment reports' : 'Turn research into your next decision.' }}</h1>
        <p>{{ mode === 'reports' ? 'Find an experiment, then explore its reports, audience, and recorded activity.' : 'Pick up your latest experiment or bring a new question to chat.' }}</p>
      </div>
      <button class="ws-btn" :disabled="loading || insightsLoading" @click="refreshAll"><RefreshCw :size="15" />{{ loading || insightsLoading ? 'Refreshing…' : 'Refresh' }}</button>
    </header>

    <div class="overview-stats" role="group" aria-label="Workspace totals">
      <article><span><FolderOpen :size="16" />Saved runs</span><strong>{{ loading ? '…' : number(runs.length) }}</strong><small>All experiments in this workspace</small></article>
      <article><span><UsersRound :size="16" />Simulated participants</span><strong>{{ loading ? '…' : knownPeople.length ? number(totalPeople) : '—' }}</strong><small>Recorded across {{ knownPeople.length }} runs; people may overlap</small></article>
      <article><span><CircleCheck :size="16" />Reached a decision</span><strong>{{ loading ? '…' : number(decided.count) }}</strong><small>{{ decided.line || 'No run has a recorded decision yet' }}</small></article>
      <article><span><FolderOpen :size="16" />Projects</span><strong>{{ loading ? '…' : number(projects.length) }}</strong><small>Related chats and research, organized together</small></article>
    </div>

    <AudienceWorldMap v-if="showInsights && geography" :geography="geography" :theme="theme" />

    <LiveNow v-if="showInsights" :runs="liveRuns" @changed="loadInsights" />
    <p v-if="showInsights && insightsError" class="ovi-error" role="status">Couldn’t load the cross-run summary. {{ insightsError }} <button type="button" class="overview-link" @click="loadInsights">Try again</button></p>

    <div v-if="runs.length" class="overview-insights">
      <section class="overview-panel overview-next" aria-labelledby="latest-heading">
        <div class="overview-section-title"><h2 id="latest-heading">{{ latestDecision ? 'Latest saved decision' : 'Continue your latest experiment' }}</h2><span>{{ date(featuredRun) }}</span></div>
        <span v-if="latestDecision" class="overview-decision" :class="decisionClass(latestDecision.decision)">{{ decisionLabel(latestDecision.decision) }}</span><h3>{{ featuredRun.title || featuredRun.name }}</h3><p>{{ featuredRun.summary || 'Open the saved reports to explore buyer responses, recorded activity, and the evidence behind this experiment.' }}</p>
        <div class="overview-result-actions"><button class="overview-result-primary" @click="$emit('select-run', featuredRun.name)">Explore results <ArrowUpRight :size="15" /></button><RouterLink :to="{path:'/',query:{run:featuredRun.name,show:'audience'}}"><Globe2 :size="15" />Explore the audience</RouterLink></div>
        <p class="overview-source-note">These conclusions come from simulated participants. Use real outcomes to validate a decision.</p>
      </section>
      <section class="overview-panel" aria-labelledby="decision-heading">
        <div class="overview-section-title"><h2 id="decision-heading">What your experiments concluded</h2></div>
        <p class="overview-chart-note">Number of saved runs by recorded decision, including runs without one.</p>
        <EChart :option="decisionChart" :height="205" :theme="theme" label="Saved run counts grouped by recorded decision; runs without decisions are included" />
      </section>
    </div>

    <div v-if="showInsights && insights.total_runs" class="ovi-grid">
      <ActivityCalendar :activity="insights.activity" :selected="day" @select-day="selectDay" />
      <IntentPanel :intent="insights.intent" />
      <ObjectionsPanel :objections="insights.objections" />
      <AudiencesPanel :segments="insights.segments" />
      <TrustPanel :trust="insights.trust" :forecasts="insights.forecasts" :total-runs="insights.total_runs" />
      <SpendPanel :spend="insights.spend" />
    </div>

    <details v-if="activeRuns.length" class="overview-active" aria-labelledby="active-heading">
      <summary class="overview-section-title"><h2 id="active-heading">{{ activeRuns.length }} {{ activeRuns.length === 1 ? 'run' : 'runs' }} didn’t record a finish</h2><span class="overview-live">Their last saved status still said running. Open one to see what was saved.</span></summary>
      <button v-for="run in activeRuns" :key="run.name" class="overview-active-run" @click="$emit('select-run', run.name)">
        <div><span class="overview-status-dot" aria-hidden="true"></span><strong>{{ run.title || run.name }}</strong><span>{{ state(run) }}</span></div>
        <div class="overview-active-meta"><span v-if="finite(run.current_round)">Round {{ run.current_round }}<template v-if="finite(run.total_rounds)"> of {{ run.total_rounds }}</template></span><span v-if="finite(run.progress_percent)">{{ Math.round(run.progress_percent) }}%</span></div>
        <progress v-if="finite(run.progress_percent)" :value="Math.min(100, Math.max(0, run.progress_percent))" max="100" :aria-label="`${run.title || run.name} progress`"></progress>
      </button>
    </details>

    <section v-if="mode !== 'reports' && (projects.length || !runs.length)" class="overview-projects" aria-labelledby="overview-projects-heading"><div class="overview-section-title"><div><h2 id="overview-projects-heading">Your projects</h2><p>Continue a conversation with its product context and instructions.</p></div><RouterLink class="overview-link" to="/workspace/projects">{{ projects.length ? 'View all projects' : 'Manage projects' }}<ArrowUpRight :size="14" /></RouterLink></div><div v-if="projects.length" class="overview-project-grid"><RouterLink v-for="project in projects.slice(0,3)" :key="project.id" :to="{path:'/',query:{project:project.id}}"><FolderOpen :size="19" /><div><h3>{{ project.name }}</h3><p>{{ project.description || 'Open this project to continue your research.' }}</p><small>{{ project.chat_ids?.length || 0 }} linked chats · {{ project.run_names?.length || 0 }} linked runs</small></div><ChevronRight :size="16" /></RouterLink></div><RouterLink v-else class="overview-project-empty" :to="{path:'/',query:{action:'project'}}"><FolderPlus :size="23" /><span><strong>Create a space for your next idea</strong><small>Keep related conversations and instructions in one project.</small></span><Plus :size="18" /></RouterLink></section>

    <section ref="runsSection" class="overview-runs" aria-labelledby="runs-heading">
      <div class="overview-section-title"><div><h2 id="runs-heading">All experiments</h2><p>Open a run for its saved reports, 3D audience, and recorded agents.</p></div><button v-if="runs.length" class="ws-btn" @click="exportRuns"><Download :size="15" />Export index</button></div>
      <div class="overview-toolbar">
        <label class="overview-search"><Search :size="16" aria-hidden="true" /><input v-model="search" type="search" aria-label="Search experiment names and summaries" placeholder="Search names or saved summaries…" /></label>
        <label class="overview-filter"><span class="sr-only">Filter by decision</span><select v-model="decision"><option value="">All decisions</option><option v-for="label in decisionOptions" :key="label" :value="label">{{ decisionLabel(label) }}</option></select></label>
        <label class="overview-filter"><span class="sr-only">Sort experiments</span><select v-model="sort"><option value="latest">Latest first</option><option value="name">Name A–Z</option><option value="people">Most participants</option></select></label>
        <button v-if="day" type="button" class="ovi-chip" :aria-label="`Showing runs saved on ${dayText}. Clear the day filter`" @click="day = ''"><CalendarDays :size="13" aria-hidden="true" />{{ dayText }}<X :size="13" aria-hidden="true" /></button>
      </div>
      <LoadingSkeleton v-if="loading && !runs.length" variant="cards" :lines="3" label="Loading saved experiments" />
      <div v-else-if="!runs.length" class="overview-empty"><FlaskConical :size="32" /><h3>Start with a decision you need to make.</h3><p>Describe your product, audience, and alternatives in chat. MarketMirror can help prepare a test, then show its saved results here.</p><RouterLink :to="{path:'/',query:{prompt:'Help me plan a market test. Ask about my product, target audience, and decision.'}}" class="ws-btn primary">Plan a test in chat<ArrowUpRight :size="15" /></RouterLink><RouterLink class="overview-link" to="/workspace/skills">Explore all skills</RouterLink></div>
      <template v-else-if="filteredRuns.length">
        <div class="overview-table-wrap" tabindex="0" role="region" aria-label="Saved experiments table, scrolls sideways"><table class="overview-table"><thead><tr><th scope="col">Experiment</th><th scope="col">Decision</th><th scope="col">Participants</th><th scope="col">Files</th><th scope="col">Updated</th><th scope="col"><span class="sr-only">Open</span></th></tr></thead><tbody>
          <tr v-for="run in filteredRuns" :key="run.name">
            <td><button class="overview-run-title" :title="run.title || run.name" @click="$emit('select-run', run.name)"><span class="overview-run-icon"><FlaskConical :size="17" /></span><span><strong>{{ run.title || run.name }}</strong><small>{{ run.name }}</small></span></button></td>
            <td><span class="overview-decision-text" :class="decisionClass(run.decision)">{{ decisionLabel(run.decision) }}</span><small v-if="isActive(run)" class="overview-run-status">{{ state(run) }}</small></td>
            <td class="overview-numeric">{{ finite(run.people) ? number(run.people) : '—' }}</td><td class="overview-numeric">{{ finite(run.file_count) ? number(run.file_count) : '—' }}</td><td class="overview-date">{{ date(run) }}</td>
            <td><div class="overview-row-actions"><RouterLink class="overview-open" :to="{path:'/',query:{run:run.name,show:'audience'}}" :aria-label="`Explore the 3D audience for ${run.title || run.name}`" title="3D audience"><Globe2 :size="16" /></RouterLink><RouterLink class="overview-open" :to="{path:'/',query:{run:run.name,show:'thinking'}}" :aria-label="`Read buyer responses for ${run.title || run.name}`" title="Buyer responses"><MessageSquare :size="16" /></RouterLink><button class="overview-open" :aria-label="`Open results for ${run.title || run.name}`" title="Open results" @click="$emit('select-run', run.name)"><ArrowUpRight :size="17" /></button></div></td>
          </tr>
        </tbody></table></div>
        <p class="overview-table-note">{{ filteredRuns.length }} of {{ runs.length }} runs · Participant counts represent simulated people.</p>
      </template>
      <div v-else class="overview-empty"><Search :size="25" /><h3>No experiments match.</h3><button class="overview-link" @click="search = ''; decision = ''; day = ''">Clear filters</button></div>
    </section>


  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Activity, ArrowUpRight, CalendarDays, CircleCheck, Download, Files, FlaskConical, FolderOpen, FolderPlus, Globe2, MessageSquare, ChevronRight, Plus, RefreshCw, Search, UsersRound, X } from 'lucide-vue-next'
import EChart from './EChart.vue'
import LoadingSkeleton from './LoadingSkeleton.vue'
import ActivityCalendar from './overview/ActivityCalendar.vue'
import { defineAsyncComponent } from 'vue'
const AudienceWorldMap = defineAsyncComponent(() => import('./overview/AudienceWorldMap.vue'))
import IntentPanel from './overview/IntentPanel.vue'
import ObjectionsPanel from './overview/ObjectionsPanel.vue'
import AudiencesPanel from './overview/AudiencesPanel.vue'
import TrustPanel from './overview/TrustPanel.vue'
import SpendPanel from './overview/SpendPanel.vue'
import LiveNow from './overview/LiveNow.vue'
import { api } from '../../workspace/api.js'
import { namesOnDay, normalizeInsights, pollable, runSignature } from '../../workspace/overviewInsights.js'

const props = defineProps({ runs: { type: Array, default: () => [] }, projects: { type: Array, default: () => [] }, mode: { type: String, default: 'dashboard' }, provider: { type: Object, default: () => ({}) }, loading: Boolean, theme: { type: String, default: 'light' } })
const emit = defineEmits(['refresh', 'select-run'])
const search = ref(''), decision = ref(''), sort = ref('latest'), day = ref('')
const runsSection = ref(null)

// Cross-run insights (GET /api/runs/insights): loaded once on the dashboard, then again with the Refresh button.
const insights = ref(normalizeInsights(null))
const insightsLoaded = ref(false), insightsLoading = ref(false), insightsError = ref('')
const showInsights = computed(() => props.mode !== 'reports')
/** Audience geography across runs, ready to pass to the world map in the slot above (countries and cities). */
const geography = computed(() => insights.value.geography)
const liveRuns = computed(() => pollable(insights.value.running))
const dayNames = computed(() => (day.value ? namesOnDay(insights.value.activity, day.value) : null))
const dayText = computed(() => { const [y, m, d] = day.value.split('-').map(Number); return y ? new Date(y, m - 1, d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '' })
async function loadInsights() {
  if (insightsLoading.value) return
  insightsLoading.value = true
  try {
    insights.value = normalizeInsights(await api('/api/runs/insights'))
    insightsError.value = ''
    if (day.value && !insights.value.activity.some(a => a.date === day.value)) day.value = ''
  } catch (e) {
    insightsError.value = e?.message || ''
  } finally {
    insightsLoaded.value = true
    insightsLoading.value = false
  }
}
function refreshAll() { emit('refresh'); if (showInsights.value) loadInsights() }
function selectDay(value) {
  day.value = value
  if (value) nextTick(() => runsSection.value?.scrollIntoView({ behavior: globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }))
}
onMounted(() => { if (showInsights.value) loadInsights() })
watch(showInsights, (on) => { if (on && !insightsLoaded.value) loadInsights() })
// The run list polls in the background; a run started or finished elsewhere
// must reach Live now and the cross-run panels without pressing Refresh.
watch(() => runSignature(props.runs), (next, previous) => {
  if (previous !== undefined && next !== previous && showInsights.value) loadInsights()
})
defineExpose({ geography })
const finite = value => typeof value === 'number' && Number.isFinite(value)
const number = value => new Intl.NumberFormat().format(value)
const normalizedDecision = value => typeof value === 'string' && value.trim() ? value.trim().toLowerCase() : 'unrecorded'
const decisionLabel = value => { const text = normalizedDecision(value); return text === 'unrecorded' ? 'No decision' : text.replaceAll('_', ' ').replaceAll('-', ' ').replace(/^./, c => c.toUpperCase()) }
const decisionClass = value => { const d = normalizedDecision(value); return /^(go|launch|proceed|test|test_small)$/.test(d) ? 'positive' : /^(no_go|no-go|stop|reject)$/.test(d) ? 'negative' : d === 'unrecorded' ? '' : 'neutral' }
const state = run => String(run.status || 'Saved').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase())
const isActive = run => /^(running|preparing|processing|pending|queued|in_progress)$/i.test(String(run.status || ''))
const activeRuns = computed(() => props.runs.filter(isActive))
const knownPeople = computed(() => props.runs.filter(r => finite(r.people)))
const knownFiles = computed(() => props.runs.filter(r => finite(r.file_count)))
const totalPeople = computed(() => knownPeople.value.reduce((sum, r) => sum + r.people, 0))
const totalFiles = computed(() => knownFiles.value.reduce((sum, r) => sum + r.file_count, 0))
const timestamp = run => { const iso = run.updated_at ? new Date(run.updated_at).getTime() : NaN; return Number.isFinite(iso) ? iso : finite(run.mtime) ? run.mtime * 1000 : 0 }
const date = run => { const t = timestamp(run); return t ? new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'Not recorded' }
const ordered = computed(() => [...props.runs].sort((a, b) => timestamp(b) - timestamp(a)))
const latestDecision = computed(() => ordered.value.find(r => normalizedDecision(r.decision) !== 'unrecorded'))
const featuredRun = computed(() => latestDecision.value || ordered.value[0])
const decisionOptions = computed(() => [...new Set(props.runs.map(r => normalizedDecision(r.decision)))].sort())
const filteredRuns = computed(() => {
  const q = search.value.toLowerCase().trim()
  return props.runs.filter(r => (!q || `${r.title || ''} ${r.name || ''} ${r.summary || ''}`.toLowerCase().includes(q)) && (!decision.value || normalizedDecision(r.decision) === decision.value) && (!dayNames.value || dayNames.value.has(r.name))).sort((a, b) => sort.value === 'name' ? String(a.title || a.name).localeCompare(String(b.title || b.name)) : sort.value === 'people' ? (finite(b.people) ? b.people : -1) - (finite(a.people) ? a.people : -1) : timestamp(b) - timestamp(a))
})
const decided = computed(() => {
  const counts = new Map()
  for (const run of props.runs) { const d = normalizedDecision(run.decision); if (d !== 'unrecorded') counts.set(d, (counts.get(d) || 0) + 1) }
  const parts = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([d, n]) => `${n} ${decisionLabel(d).toLowerCase()}`)
  const none = props.runs.length - [...counts.values()].reduce((a, b) => a + b, 0)
  return { count: props.runs.length - none, line: parts.length ? parts.join(' · ') + (none ? ` · ${none} without one` : '') : '' }
})
const decisionChart = computed(() => {
  const colors = palette()
  const text = colors.text, muted = colors.muted, line = colors.line
  const counts = new Map()
  for (const run of props.runs) { const key = normalizedDecision(run.decision); counts.set(key, (counts.get(key) || 0) + 1) }
  const rows = [...counts.entries()].sort((a, b) => a[1] - b[1])
  return { animation: !globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches, textStyle: { fontFamily: 'inherit', color: text }, grid: { left: 0, right: 32, top: 10, bottom: 4, containLabel: true }, tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true }, xAxis: { type: 'value', minInterval: 1, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } }, yAxis: { type: 'category', data: rows.map(([d]) => decisionLabel(d)), axisLabel: { color: text, width: 140, overflow: 'truncate' }, axisLine: { show: false }, axisTick: { show: false } }, series: [{ name: 'Saved runs', type: 'bar', barMaxWidth: 24, label: { show: true, position: 'right', color: text }, itemStyle: { color: colors.accent, borderRadius: [0, 4, 4, 0] }, data: rows.map(([decision, count]) => ({ value: count, itemStyle: { color: decision === 'unrecorded' ? colors.data : decisionClass(decision) === 'positive' ? colors.yes : decisionClass(decision) === 'negative' ? colors.no : colors.maybe } })) }] }
})
function exportRuns() {
  const escape = value => `"${String(value ?? '').replaceAll('"', '""')}"`
  const rows = [['Run', 'Title', 'Decision', 'Participants', 'Artifacts', 'Status', 'Updated'], ...filteredRuns.value.map(r => [r.name, r.title, r.decision, r.people, r.file_count, r.status, r.updated_at])]
  const url = URL.createObjectURL(new Blob([rows.map(row => row.map(escape).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = 'marketmirror-run-index.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<style scoped>
.overview-projects{min-width:0}.overview-project-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.overview-project-grid>a{display:flex;align-items:flex-start;gap:12px;padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--panel);min-width:0;color:var(--text);text-decoration:none}.overview-project-grid>a>svg{flex-shrink:0;color:var(--accent)}.overview-project-grid>a>svg:last-child{margin-left:auto;width:14px;color:var(--muted)}.overview-project-grid>a>div{min-width:0}.overview-project-grid h3{font-size:13px;font-weight:550;margin-bottom:7px;overflow-wrap:anywhere}.overview-project-grid p{color:var(--muted);font-size:11px;line-height:1.7;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.overview-project-grid small{display:block;font-size:10px;color:var(--muted);margin-top:12px}.overview-project-grid>a:hover{border-color:var(--accent)}.overview-project-empty{display:flex;align-items:center;gap:15px;padding:20px 22px;border:1px dashed var(--line);border-radius:14px;background:var(--panel);color:var(--text);text-decoration:none}.overview-project-empty>svg{color:var(--accent);flex-shrink:0}.overview-project-empty>svg:last-child{margin-left:auto}.overview-project-empty strong,.overview-project-empty small{display:block}.overview-project-empty strong{font-size:13px;font-weight:550}.overview-project-empty small{font-size:11px;line-height:1.6;color:var(--muted);margin-top:5px}.overview-result-actions{display:flex;flex-wrap:wrap;align-items:center;gap:13px;margin-top:auto}.overview-result-actions button,.overview-result-actions a{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:10px 12px;border:0;border-radius:9px;font:inherit;font-size:11px;cursor:pointer;color:var(--muted);background:transparent;text-decoration:none}.overview-result-actions button.overview-result-primary{background:var(--accent);color:white}.overview-next>p.overview-source-note{font-size:10px;line-height:1.7;margin:13px 0 0;max-height:none;overflow:visible}.overview-chart-note{color:var(--muted);font-size:11px;line-height:1.7;margin-bottom:10px}.overview-decision-text{font-size:11px;font-weight:550;white-space:nowrap;color:var(--muted)}.overview-decision-text.positive{color:var(--accent)}.overview-decision-text.negative{color:var(--no)}.overview-decision-text.neutral{color:var(--maybe)}@media(max-width:1000px){.overview-project-grid{grid-template-columns:1fr}}@media(max-width:600px){.overview-result-actions{gap:5px}.overview-result-actions button,.overview-result-actions a{font-size:10px}.overview-project-empty{padding:17px}.overview-project-grid>a{padding:16px}}
.overview{max-width:1360px;margin:0 auto;padding:36px 40px 24px;display:flex;flex-direction:column;gap:26px}.overview-heading{display:flex;align-items:center;justify-content:space-between;gap:20px}.overview-heading h1{font-size:30px;font-weight:600;letter-spacing:-1px;line-height:1.25;margin-bottom:9px}.overview-heading p{font-size:14px;color:var(--muted);line-height:1.6}.ws-btn{display:inline-flex;align-items:center;justify-content:center;gap:7px}.overview-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.overview-stats article{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;min-width:0;display:flex;flex-direction:column;gap:12px}.overview-stats article>span{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}.overview-stats strong{font-size:29px;line-height:1.1;font-weight:600;letter-spacing:-.7px;font-variant-numeric:tabular-nums}.overview-stats small{font-size:11px;color:var(--muted);line-height:1.5}.overview-insights{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}.overview-panel{border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:21px;min-width:0}.overview-section-title{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}.overview-section-title h2{font-size:15px;font-weight:600}.overview-section-title>span{font-size:11px;color:var(--muted)}.overview-section-title p{margin-top:6px;color:var(--muted);font-size:12px;line-height:1.6}.overview-next{display:flex;flex-direction:column;align-items:flex-start}.overview-next .overview-section-title{width:100%}.overview-decision{font-size:12px;font-weight:550;color:var(--accent);margin-top:6px}.overview-next h3{font-size:20px;font-weight:550;letter-spacing:-.4px;margin:8px 0;overflow-wrap:anywhere}.overview-next>p{font-size:13px;line-height:1.8;color:var(--muted);margin-bottom:15px;max-height:110px;overflow:auto}.overview-link{display:inline-flex;align-items:center;gap:6px;background:none;border:0;color:var(--accent);font-size:12px;text-decoration:none;padding:5px 0;cursor:pointer;margin-top:auto}.overview-runs{min-width:0}.overview-toolbar{display:flex;gap:10px;align-items:center;margin-bottom:15px}.overview-search{display:flex;gap:9px;align-items:center;flex:1;color:var(--muted);border:1px solid var(--line);border-radius:8px;padding:0 11px;background:var(--panel);min-width:100px}.overview-search input{width:100%;border:0;background:transparent;padding:10px 0;font-size:12px;min-width:0;color:var(--text)}.overview-filter select{background:var(--panel);color:var(--text);font-size:12px;padding:10px 28px 10px 11px;border:1px solid var(--line);border-radius:8px;max-width:180px}.overview-table-wrap{position:relative;overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel)}.overview-table{border-collapse:collapse;width:100%;font-size:12px;text-align:left}.overview-table th{font-weight:500;color:var(--muted);background:var(--panel-2,var(--bg));padding:12px 16px;font-size:11px;white-space:nowrap}.overview-table td{padding:14px 16px;border-top:1px solid var(--line);vertical-align:middle}.overview-table tbody tr:hover{background:var(--panel-2,var(--bg))}.overview-run-title{display:flex;gap:11px;align-items:center;background:transparent;border:0;color:var(--text);text-align:left;cursor:pointer;max-width:100%;min-width:170px}.overview-run-title strong{display:block;font-weight:550;font-size:12px;max-width:300px;overflow-wrap:anywhere}.overview-run-title small{display:block;color:var(--muted);font-size:10px;margin-top:4px;max-width:300px;overflow-wrap:anywhere}.overview-run-icon{display:grid;place-items:center;width:34px;height:34px;flex-shrink:0;background:var(--accent-2);border-radius:8px;color:var(--accent)}.overview-badge{display:inline-block;padding:4px 8px;border:1px solid var(--line);border-radius:6px;color:var(--muted);font-size:10px;white-space:nowrap;background:var(--panel-2,var(--bg))}.overview-badge.positive{color:var(--accent);background:var(--accent-2)}.overview-badge.negative{color:var(--text)}.overview-badge.neutral{color:var(--text)}.overview-run-status{display:block;color:var(--muted);font-size:10px;margin-top:5px}.overview-numeric{font-variant-numeric:tabular-nums}.overview-date{white-space:nowrap;color:var(--muted);font-size:11px}.overview-open{display:grid;place-items:center;padding:6px;border:0;background:transparent;border-radius:5px;color:var(--muted);cursor:pointer}.overview-open:hover{color:var(--accent);background:var(--accent-2)}.overview-table-note{margin-top:12px;font-size:11px;color:var(--muted)}.overview-empty{min-height:200px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:13px;padding:30px;color:var(--muted);border:1px dashed var(--line);border-radius:12px;background:var(--panel)}.overview-empty h3{font-size:16px;color:var(--text);font-weight:550}.overview-empty p{font-size:13px;max-width:440px;line-height:1.7}.overview-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;color:var(--muted);font-size:11px;padding-top:6px}.overview-footer>span,.overview-footer>a{display:flex;gap:7px;align-items:center}.overview-footer>a{color:var(--accent);white-space:nowrap;text-decoration:none}.overview-active{padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:12px}.overview-active-run{display:block;width:100%;text-align:left;padding:14px 0;background:none;border:0;border-top:1px solid var(--line);cursor:pointer;color:var(--text)}.overview-active-run>div{display:flex;gap:9px;align-items:center;font-size:12px;flex-wrap:wrap}.overview-active-run strong{font-weight:550}.overview-active-run span:not(.overview-status-dot){color:var(--muted);font-size:11px}.overview-status-dot{width:6px;height:6px;border-radius:50%;background:var(--accent)}.overview-active-meta{margin:7px 0 0 15px}.overview-active-run progress{width:100%;height:5px;accent-color:var(--accent);margin-top:10px}.overview-live{font-size:11px;color:var(--muted)}
@media(min-width:1600px){.overview{padding-top:45px}}@media(max-width:1100px){.overview{padding:26px 24px}.overview-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-insights{grid-template-columns:minmax(0,1fr)}.overview-next>p{max-height:none}}@media(max-width:600px){.overview{padding:24px 15px;gap:22px}.overview-heading{align-items:flex-start}.overview-heading h1{font-size:25px}.overview-heading p{font-size:12px}.overview-heading>.ws-btn{font-size:11px;padding:8px}.overview-stats{gap:9px}.overview-stats article{padding:14px;gap:10px}.overview-stats article>span{font-size:11px;align-items:flex-start}.overview-stats strong{font-size:25px}.overview-stats small{font-size:10px}.overview-toolbar{flex-wrap:wrap}.overview-search{flex-basis:100%}.overview-filter{flex:1}.overview-filter select{width:100%;max-width:none}.overview-panel{padding:16px}.overview-footer{flex-direction:column;align-items:flex-start}.overview-section-title{align-items:flex-start}.overview-table td,.overview-table th{padding:12px}.overview-empty{padding:25px 15px}}
.overview-next h3{font-size:19px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.overview-next>p:not(.overview-source-note){display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;max-height:none}.overview{gap:23px}.overview-stats article{padding:18px;gap:11px}.overview-insights{align-items:stretch}
.overview-row-actions{display:flex;gap:3px;align-items:center}.overview-run-title strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.overview-open{text-decoration:none}
</style>
