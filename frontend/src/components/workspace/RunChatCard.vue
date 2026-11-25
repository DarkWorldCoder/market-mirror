<template>
  <section class="run-chat-card" :aria-label="`Saved run: ${stats.title || name}`">
    <LoadingSkeleton v-if="loading" variant="cards" :lines="2" label="Opening the saved run" />
    <p v-else-if="error" class="rcc-error" role="alert">{{ error }} <button type="button" class="rcc-link" @click="load">Try again</button></p>
    <template v-else-if="detail">
      <header class="rcc-head">
        <div class="rcc-title">
          <span class="rcc-kicker"><FileChartColumn :size="13" aria-hidden="true" />Saved run</span>
          <h3 :title="stats.title || name">{{ stats.title || name }}</h3>
        </div>
        <span v-if="stats.decision" class="dw-decision rcc-verdict" :class="stats.tone">Simulated verdict: <b>{{ stats.decisionLabel }}</b></span>
        <span v-else class="dw-decision rcc-verdict">No verdict saved</span>
      </header>
      <p v-if="stats.summary" class="rcc-summary">{{ stats.summary }}</p>
      <ul v-if="stats.numbers.length" class="rcc-numbers" aria-label="Key numbers, simulated">
        <li v-for="n in stats.numbers" :key="n.key"><b>{{ n.value }}</b><span>{{ n.label }}</span><small>{{ n.note ? `${n.note} · ` : '' }}simulated</small></li>
      </ul>

      <div class="rcc-tabs workspace-modal-tabs" role="tablist" :aria-label="`Views of ${stats.title || name}`" @keydown="onTabKey">
        <button v-for="t in tabs" :id="`${uid}-tab-${t.id}`" :key="t.id" type="button" role="tab" :aria-selected="tab === t.id" :aria-controls="`${uid}-panel-${t.id}`" :tabindex="tab === t.id ? 0 : -1" @click="select(t.id)">{{ t.label }}</button>
      </div>

      <template v-for="t in tabs" :key="t.id">
        <div v-if="visited.has(t.id)" v-show="tab === t.id" :id="`${uid}-panel-${t.id}`" class="rcc-panel" role="tabpanel" :aria-labelledby="`${uid}-tab-${t.id}`" tabindex="0">
          <template v-if="t.id === 'results'">
            <LoadingSkeleton v-if="results.loading" variant="cards" :lines="4" label="Loading the results" />
            <p v-else-if="results.error" class="rcc-error" role="alert">{{ results.error }} <button type="button" class="rcc-link" @click="loadResults">Try again</button></p>
            <ReadableReport v-else-if="results.report" :report="results.report" />
            <p v-else class="rcc-empty">No plain-language results in this run yet. Browse the saved reports below.</p>
            <div v-if="detail.files?.length" class="rcc-more">
              <button type="button" class="rcc-link" :aria-expanded="allReports" @click="allReports = !allReports">{{ allReports ? 'Hide saved reports' : `Browse all ${detail.files.length} saved reports` }}</button>
            </div>
            <ReportBrowser v-if="allReports" :name="name" :files="detail.files || []" initial-view="reports" :theme="theme" review-disabled />
          </template>

          <RunAudienceCard v-else-if="t.id === 'market'" class="rcc-audience" :name="name" :theme="theme" />

          <PeopleExplorer v-else-if="t.id === 'people'" compact :name="name" :theme="theme" :initial-filters="peopleFilters" @ask="(p) => act('ask', p)" />

          <template v-else-if="t.id === 'thinking'">
            <LoadingSkeleton v-if="buyers.loading" :lines="5" label="Loading what the buyers said" />
            <p v-else-if="buyers.error" class="rcc-error" role="alert">{{ buyers.error }} <button type="button" class="rcc-link" @click="loadBuyers">Try again</button></p>
            <p v-else-if="buyers.loaded && !buyers.survey && !buyers.feed && !buyers.stream" class="rcc-empty">No buyer survey or saved thoughts in this run.</p>
            <BuyerResponses v-else-if="buyers.loaded" :survey="buyers.survey" :feed="buyers.feed" :stream="buyers.stream" :index="buyers.index" :initial-filters="responseFilters" @ask="askById" />
          </template>

          <template v-else-if="t.id === 'activity'">
            <LoadingSkeleton v-if="activity.loading" :lines="6" label="Loading the recorded activity" />
            <template v-else-if="activity.loaded">
              <RunActivity :timeline="activity.timeline" :panel="activity.panel" :agents="activity.agents" :theme="theme" />
              <p class="rcc-note">Recorded actions from the simulation. Saved results do not mean anything is running now.</p>
            </template>
          </template>

          <SocialFeedPlatform v-else-if="t.id === 'feed' && feedReady" :name="name" :files="detail.files || []" />
          <p v-else-if="t.id === 'feed'" class="rcc-empty">No social posts were saved in this run.</p>

          <LandingAnalysis v-else-if="t.id === 'landing'" :name="name" :files="detail.files || []" :title="stats.title || name" :level="4" @prompt="landingPrompt" />

          <template v-else-if="t.id === 'brain'">
            <LoadingSkeleton v-if="brain.loading" :lines="4" label="Loading the brain response" />
            <BrainResponseSection v-else-if="brainReady" :brain="brain.data" :feed="brain.feed" :theme="theme" />
            <p v-else-if="brain.loaded" class="rcc-empty">This run saved no brain response. It is an optional research add-on (TRIBE v2) that runs on your own server.</p>
          </template>
        </div>
      </template>

      <footer class="rcc-actions" aria-label="Run actions">
        <button type="button" :title="spendHint" @click="act('ask')"><MessageCircleQuestion :size="15" aria-hidden="true" />Ask a person</button>
        <button type="button" :title="spendHint" @click="act('focus')"><UsersRound :size="15" aria-hidden="true" />Run a focus group</button>
        <Popover v-model:open="compareOpen">
          <PopoverTrigger as-child><button type="button" :disabled="!choices.length" :title="choices.length ? 'Compare side by side, free' : 'Save a second run to compare'"><GitCompare :size="15" aria-hidden="true" />Compare with…</button></PopoverTrigger>
          <PopoverContent class="ws-overlay rcc-compare-menu" :data-theme="theme" align="start">
            <p>Compare side by side. Free, no model call.</p>
            <button v-for="c in choices" :key="c.name" type="button" @click="compareWith(c.name)"><span>{{ c.title }}</span><small v-if="c.decision" class="dw-decision" :class="decisionTone(c.decision)">{{ decisionText(c.decision) }}</small></button>
          </PopoverContent>
        </Popover>
        <RouterLink :to="{ path: `/workspace/runs/${name}`, query: fullPageTab(tab) === 'results' ? {} : { view: fullPageTab(tab) } }"><ExternalLink :size="15" aria-hidden="true" />Open full page</RouterLink>
        <button v-if="downloadFile" type="button" :disabled="downloading" @click="save"><Download :size="15" aria-hidden="true" />{{ downloading ? 'Downloading…' : 'Download report' }}</button>
      </footer>
      <p class="rcc-note rcc-foot">Asking a person and focus groups use model calls. You see the cost and approve it first.</p>
    </template>
  </section>
</template>
<script setup>
import { computed, defineAsyncComponent, nextTick, reactive, ref, useId, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Download, ExternalLink, FileChartColumn, GitCompare, MessageCircleQuestion, UsersRound } from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover'
import LoadingSkeleton from './LoadingSkeleton.vue'
import ReadableReport from './ReadableReport.vue'
import { api, download } from '../../workspace/api.js'
import { presentReport } from '../../workspace/reportPresentation.js'
import { decisionText, decisionTone } from '../../workspace/compareRuns.js'
import { brainRows } from '../../workspace/brainResponse.js'
import { cardTabs, compareChoices, fullPageTab, hasFeed, moveTab, reportDownloadFile, resultsFile, runCardStats, tabForView } from '../../workspace/runCard.js'
const RunAudienceCard = defineAsyncComponent(() => import('./RunAudienceCard.vue'))
const PeopleExplorer = defineAsyncComponent(() => import('./PeopleExplorer.vue'))
const SocialFeedPlatform = defineAsyncComponent(() => import('./SocialFeedPlatform.vue'))
const ReportBrowser = defineAsyncComponent(() => import('./ReportBrowser.vue'))
const LandingAnalysis = defineAsyncComponent(() => import('./LandingAnalysis.vue'))
const BuyerResponses = defineAsyncComponent(() => import('./BuyerResponses.vue'))
const RunActivity = defineAsyncComponent(() => import('./RunActivity.vue'))
const BrainResponseSection = defineAsyncComponent(() => import('./BrainResponseSection.vue'))

const props = defineProps({
  name: { type: String, required: true },
  initialTab: { type: String, default: 'results' },
  initialVerdict: { type: String, default: '' },
  // filters from the chat for the People and Buyer responses tabs ({ country, segment, verdict, objection, query })
  filters: { type: Object, default: null },
  runs: { type: Array, default: () => [] },
  theme: { type: String, default: 'light' }
})
const emit = defineEmits(['action', 'update:tab', 'loaded'])
const uid = useId()
const detail = ref(null), loading = ref(true), error = ref('')
const tab = ref(tabForView(props.initialTab)), visited = reactive(new Set([tab.value]))
const allReports = ref(false), compareOpen = ref(false), downloading = ref(false)
const results = reactive({ loading: false, error: '', report: null })
const buyers = reactive({ loading: false, error: '', survey: null, feed: null, stream: null, index: [], loaded: false })
const activity = reactive({ loading: false, loaded: false, timeline: [], agents: [], panel: null })
const brain = reactive({ loading: false, loaded: false, data: null, feed: null })
const startVerdict = ['yes', 'maybe', 'no'].includes(props.initialVerdict) ? props.initialVerdict : ''
const peopleFilters = computed(() => (props.filters && Object.keys(props.filters).length ? props.filters : null))
// Buyer responses has no country chip: a country becomes a search over names and places
const responseFilters = computed(() => {
  const f = { ...(props.filters || {}) }
  if (startVerdict && !f.verdict) f.verdict = startVerdict
  if (f.country && !f.query) f.query = f.country
  delete f.country; delete f.gender
  return Object.keys(f).length ? f : null
})
const spendHint = 'Uses model calls. You see the cost and approve it first.'

const stats = computed(() => runCardStats(detail.value))
const tabs = computed(() => cardTabs(detail.value?.files, tab.value))
const brainReady = computed(() => brainRows(brain.data, brain.feed).length > 0)
const choices = computed(() => compareChoices(props.runs, props.name))
const downloadFile = computed(() => reportDownloadFile(detail.value?.files))
const feedReady = computed(() => hasFeed(detail.value?.files))
const enc = () => encodeURIComponent(props.name)
let ticket = 0

async function load() {
  const mine = ++ticket
  loading.value = true; error.value = ''
  try {
    const d = await api(`/api/runs/${enc()}`)
    if (mine !== ticket) return
    detail.value = d
    emit('loaded', d)
    for (const id of visited) openTab(id)
    revealTab(tab.value)
  } catch (e) { if (mine === ticket) error.value = e.message || 'Could not open this saved run.' }
  finally { if (mine === ticket) loading.value = false }
}
async function loadResults() {
  const file = resultsFile(detail.value?.files)
  results.error = ''
  if (file === 'summary.json' && detail.value?.summary && Object.keys(detail.value.summary).length) { results.report = withoutHeaderCards(presentReport('summary.json', detail.value.summary)); return }
  if (!file) { results.report = null; return }
  results.loading = true
  try { results.report = withoutHeaderCards(presentReport(file, await api(`/api/runs/${enc()}/files/${file}`))) }
  catch (e) { results.error = e.message } finally { results.loading = false }
}
// the card header already shows the verdict, people, would buy and maybe; the Results tab keeps the rest
function withoutHeaderCards(report) {
  if (!report?.cards) return report
  return { ...report, cards: report.cards.filter((c) => !/^(decision|simulated people|people|would buy|maybe)$/i.test(String(c.label || '').trim())) }
}
// one read per saved file, shared by the tabs that need it
const reads = new Map()
function readFile(file) {
  if (!(detail.value?.files || []).includes(file)) return Promise.resolve(null)
  if (!reads.has(file)) reads.set(file, api(`/api/runs/${enc()}/files/${file}`).catch((e) => { reads.delete(file); throw e }))
  return reads.get(file)
}
async function loadBuyers() {
  buyers.error = ''; buyers.loading = true
  try {
    const [survey, feed, stream, config] = await Promise.all(['survey.json', 'feed_test.json', 'thought_stream.json', 'config.json'].map((f) => readFile(f).catch(() => null)))
    Object.assign(buyers, { survey, feed, stream, index: Array.isArray(config?.persona_index) ? config.persona_index : [], loaded: true })
  } catch (e) { buyers.error = e.message } finally { buyers.loading = false }
}
async function loadActivity() {
  activity.loading = true
  const [timeline, stats, panel] = await Promise.all(['timeline.json', 'agent_stats.json', 'analyst_panel.json'].map((f) => readFile(f).catch(() => null)))
  activity.timeline = Array.isArray(timeline) ? timeline : []
  activity.agents = Array.isArray(stats) ? stats : Array.isArray(stats?.agents) ? stats.agents : []
  activity.panel = panel && typeof panel === 'object' ? panel : null
  activity.loaded = true; activity.loading = false
}
async function loadBrain() {
  brain.loading = true
  const [data, feed] = await Promise.all(['brain_response.json', 'feed_test.json'].map((f) => readFile(f).catch(() => null)))
  Object.assign(brain, { data, feed, loaded: true, loading: false })
}
// each tab reads its own files the first time it opens
function openTab(id) {
  if (!detail.value) return
  if (id === 'results' && !results.report && !results.loading) loadResults()
  if (id === 'thinking' && !buyers.loaded && !buyers.loading) loadBuyers()
  if (id === 'activity' && !activity.loaded && !activity.loading) loadActivity()
  if (id === 'brain' && !brain.loaded && !brain.loading) loadBrain()
}
function select(id) {
  tab.value = id; visited.add(id); openTab(id); emit('update:tab', id)
  revealTab(id)
}
// on a phone the tab row scrolls sideways: keep the selected tab in view without moving the page
function revealTab(id) {
  nextTick(() => {
    const el = document.getElementById(`${uid}-tab-${id}`), row = el?.parentElement
    if (!el || !row || row.scrollWidth <= row.clientWidth) return
    const left = el.getBoundingClientRect().left - row.getBoundingClientRect().left + row.scrollLeft, right = left + el.offsetWidth
    if (left < row.scrollLeft) row.scrollLeft = Math.max(0, left - 12)
    else if (right > row.scrollLeft + row.clientWidth) row.scrollLeft = right - row.clientWidth + 12
  })
}
function onTabKey(event) {
  const next = moveTab(tabs.value, tab.value, event.key)
  if (!next) return
  event.preventDefault()
  select(next)
  nextTick(() => document.getElementById(`${uid}-tab-${next}`)?.focus())
}
watch(() => props.name, () => {
  reads.clear(); results.report = null; allReports.value = false
  Object.assign(buyers, { survey: null, feed: null, stream: null, index: [], loaded: false })
  activity.loaded = false
  Object.assign(brain, { loaded: false, data: null, feed: null })
  load()
}, { immediate: true })

// Buyer responses gives a person id; the name comes from the saved persona index
function askById(id) {
  const p = buyers.index.find((x) => String(x.agent_id) === String(id))
  act('ask', { id: String(id), name: p?.name || '' })
}
function act(type, person) { emit('action', { type, run: props.name, title: stats.value.title || props.name, ...(person ? { person } : {}) }) }
// landing analysis: a fix goes to the chat agent (cost on its approval card first); "Test a landing page" only fills the box
function landingPrompt({ text, send } = {}) { if (text) emit('action', { type: send ? 'agent-prompt' : 'draft', run: props.name, title: stats.value.title || props.name, prompt: text }) }
function compareWith(other) { compareOpen.value = false; emit('action', { type: 'compare', run: props.name, other, title: stats.value.title || props.name }) }
async function save() {
  if (!downloadFile.value) return
  downloading.value = true
  try { await download(props.name, downloadFile.value) } catch (e) { error.value = e.message } finally { downloading.value = false }
}
</script>
<style scoped>
.run-chat-card { margin-top: 14px; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); min-width: 0; overflow: hidden; box-shadow: 0 1px 2px rgb(20 20 40 / 3%); }
.run-chat-card > .ws-skeleton, .run-chat-card > .rcc-error { padding: 18px; }
.rcc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 16px 18px 0; }
.rcc-title { min-width: 0; }
.rcc-kicker { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 550; color: var(--muted); }
.rcc-title h3 { margin: 4px 0 0; font-size: 15px; font-weight: 600; line-height: 1.4; letter-spacing: -.1px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
.rcc-verdict { flex-shrink: 0; margin-top: 2px; font-size: 11.5px; font-weight: 550; line-height: 1.7; padding: 1px 10px; white-space: nowrap; }
.rcc-verdict b { font-weight: 700; }
.rcc-summary { margin: 8px 18px 0; font-size: 13px; line-height: 1.6; color: var(--text); }
.rcc-numbers { list-style: none; margin: 12px 0 0; padding: 0 18px; display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
.rcc-numbers li { display: grid; gap: 1px; padding: 9px 12px; border-radius: 11px; background: var(--panel-2); min-width: 0; }
.rcc-numbers b { font-size: 17px; font-weight: 650; line-height: 1.3; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rcc-numbers span { font-size: 12px; color: var(--text); }
.rcc-numbers small { font-size: 10.5px; color: var(--warm); }
.rcc-tabs { display: flex; flex-wrap: nowrap; gap: 2px; margin-top: 14px; padding: 4px 10px 0; border-bottom: 1px solid var(--line); overflow-x: auto; scrollbar-width: none; overscroll-behavior-x: contain; scroll-snap-type: x proximity; }
.rcc-tabs::-webkit-scrollbar { display: none; }
.rcc-tabs [role='tab'] { flex: 0 0 auto; min-height: 40px !important; padding: 8px 12px; font-size: 12.5px !important; white-space: nowrap; cursor: pointer; scroll-snap-align: start; }
.rcc-tabs [role='tab'][aria-selected='true'] { border-color: transparent !important; background: transparent !important; box-shadow: none !important; }
.rcc-tabs [role='tab']:not([aria-selected='true']):hover { color: var(--text) !important; }
.rcc-panel { padding: 16px 18px; min-width: 0; max-height: 640px; overflow: auto; overscroll-behavior: contain; }
.rcc-panel:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.rcc-panel :deep(.report-browser) { margin-top: 12px; }
.rcc-audience { margin: 0 !important; padding: 0 !important; border: 0 !important; border-radius: 0 !important; }
.rcc-panel :deep(.social-feed-platform), .rcc-panel :deep(.social-feed-card) { padding: 0; }
.rcc-more { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }
.rcc-link { padding: 0; border: 0; background: none; color: var(--accent); font: inherit; font-size: 12.5px; font-weight: 550; cursor: pointer; text-underline-offset: 3px; }
.rcc-link:hover { text-decoration: underline; }
.rcc-empty { margin: 0; padding: 18px; border: 1px dashed var(--line); border-radius: 12px; color: var(--muted); font-size: 12.5px; line-height: 1.6; text-align: center; }
.rcc-error { margin: 0; font-size: 12.5px; color: var(--text); }
.rcc-note { margin: 12px 0 0; font-size: 11px; line-height: 1.6; color: var(--muted); }
.rcc-actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 18px 0; border-top: 1px solid var(--line); }
.rcc-actions > button, .rcc-actions > a { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 6px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; font-weight: 500; text-decoration: none; cursor: pointer; white-space: nowrap; }
.rcc-actions > button:hover:not(:disabled), .rcc-actions > a:hover { background: var(--panel-2); border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); }
.rcc-actions > button:disabled { opacity: .5; cursor: not-allowed; }
.rcc-actions svg { color: var(--muted); flex-shrink: 0; }
.rcc-foot { padding: 0 18px 14px; margin-top: 8px; }
:global(.rcc-compare-menu.ws-overlay) { width: 300px !important; max-width: calc(100vw - 32px); padding: 6px !important; background: var(--panel) !important; color: var(--text) !important; border-color: var(--line) !important; border-radius: 12px !important; }
:global(.rcc-compare-menu > p) { margin: 4px 8px 6px; font-size: 11px; color: var(--muted); }
:global(.rcc-compare-menu > button) { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; min-height: 40px; padding: 8px 10px; border: 0; border-radius: 8px; background: transparent; color: var(--text); font: inherit; font-size: 13px; text-align: left; cursor: pointer; }
:global(.rcc-compare-menu > button:hover), :global(.rcc-compare-menu > button:focus-visible) { background: var(--panel-2); }
:global(.rcc-compare-menu > button > span) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
:global(.rcc-compare-menu > button > small) { flex-shrink: 0; }
@media (max-width: 600px) {
  .rcc-head { flex-direction: column; gap: 8px; padding: 14px 14px 0; }
  .rcc-summary { margin-inline: 14px; }
  .rcc-numbers { padding: 0 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rcc-tabs { padding-inline: 6px; }
  .rcc-tabs [role='tab'] { min-height: 44px !important; padding: 10px 11px; }
  .rcc-panel { padding: 14px; max-height: none; }
  .rcc-actions { padding: 12px 14px 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rcc-actions > button, .rcc-actions > a { min-height: 44px; justify-content: center; white-space: normal; text-align: center; line-height: 1.3; }
  .rcc-foot { padding: 0 14px 14px; }
}
</style>
