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
        <button v-for="t in RUN_CARD_TABS" :id="`${uid}-tab-${t.id}`" :key="t.id" type="button" role="tab" :aria-selected="tab === t.id" :aria-controls="`${uid}-panel-${t.id}`" :tabindex="tab === t.id ? 0 : -1" @click="select(t.id)">{{ t.label }}</button>
      </div>

      <template v-for="t in RUN_CARD_TABS" :key="t.id">
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

          <template v-else-if="t.id === 'thinking'">
            <LoadingSkeleton v-if="buyers.loading" :lines="5" label="Loading what the buyers said" />
            <p v-else-if="buyers.error" class="rcc-error" role="alert">{{ buyers.error }} <button type="button" class="rcc-link" @click="loadBuyers">Try again</button></p>
            <p v-else-if="!buyers.survey" class="rcc-empty">No buyer survey in this run.</p>
            <template v-else>
              <div class="rcc-filter" role="group" aria-label="Show answers by verdict">
                <button v-for="f in verdictFilters" :key="f.id" type="button" :aria-pressed="verdict === f.id" @click="verdict = f.id; shown = 8">{{ f.label }} <span>{{ f.count.toLocaleString('en-US') }}</span></button>
              </div>
              <ol v-if="responses.length" class="rcc-responses">
                <li v-for="r in responses.slice(0, shown)" :key="r.id">
                  <header><b>{{ r.who }}</b><span v-if="r.verdict" class="rcc-said" :class="r.verdict">{{ verdictWord[r.verdict] }}</span></header>
                  <p v-if="r.said" class="rcc-quote">“{{ r.said }}”</p>
                  <p v-if="r.objection" class="rcc-why"><span>Holding back:</span> {{ r.objection }}</p>
                  <p v-if="r.change" class="rcc-why"><span>Would change their mind:</span> {{ r.change }}</p>
                </li>
              </ol>
              <p v-else class="rcc-empty">No answers with words for this verdict.</p>
              <button v-if="responses.length > shown" type="button" class="rcc-link rcc-show-more" @click="shown += 8">Show 8 more of {{ (responses.length - shown).toLocaleString('en-US') }}</button>
              <p class="rcc-note">Written by a model playing each invented person. Simulated.</p>
            </template>
          </template>

          <template v-else-if="t.id === 'activity'">
            <LoadingSkeleton v-if="activity.loading" :lines="6" label="Loading the recorded activity" />
            <p v-else-if="!rounds.length && !actors.length" class="rcc-empty">No activity was saved in this run.</p>
            <template v-else>
              <ul v-if="mix.length" class="rcc-mix" aria-label="Actions recorded, simulated">
                <li v-for="m in mix.slice(0, 6)" :key="m.key"><b>{{ m.count.toLocaleString('en-US') }}</b> {{ m.label }}</li>
              </ul>
              <section v-if="rounds.length" class="rcc-rounds" aria-label="Actions by round">
                <h4>Actions by round</h4>
                <ol>
                  <li v-for="r in rounds" :key="r.round">
                    <span>Round {{ r.round }}</span>
                    <span class="rcc-bar" aria-hidden="true"><i :style="{ width: `${Math.max(2, r.share)}%` }"></i></span>
                    <b>{{ r.total.toLocaleString('en-US') }}</b>
                  </li>
                </ol>
              </section>
              <section v-if="actors.length" class="rcc-actors" aria-label="Most active people">
                <h4>Most active people</h4>
                <ol><li v-for="a in actors" :key="a.id"><b>{{ a.who }}</b><span>{{ a.detail }}</span></li></ol>
              </section>
              <p class="rcc-note">Recorded actions from the simulation. Saved results do not mean anything is running now.</p>
            </template>
          </template>

          <SocialFeedPlatform v-else-if="t.id === 'feed' && feedReady" :name="name" :files="detail.files || []" />
          <p v-else-if="t.id === 'feed'" class="rcc-empty">No social posts were saved in this run.</p>
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
        <RouterLink :to="{ path: `/workspace/runs/${name}`, query: tab === 'results' ? {} : { view: tab } }"><ExternalLink :size="15" aria-hidden="true" />Open full page</RouterLink>
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
import { RUN_CARD_TABS, actionMix, activityRounds, buyerResponses, compareChoices, hasFeed, moveTab, reportDownloadFile, resultsFile, runCardStats, tabForView, topActors, verdictCounts } from '../../workspace/runCard.js'
const RunAudienceCard = defineAsyncComponent(() => import('./RunAudienceCard.vue'))
const SocialFeedPlatform = defineAsyncComponent(() => import('./SocialFeedPlatform.vue'))
const ReportBrowser = defineAsyncComponent(() => import('./ReportBrowser.vue'))

const props = defineProps({
  name: { type: String, required: true },
  initialTab: { type: String, default: 'results' },
  initialVerdict: { type: String, default: '' },
  runs: { type: Array, default: () => [] },
  theme: { type: String, default: 'light' }
})
const emit = defineEmits(['action', 'update:tab', 'loaded'])
const uid = useId()
const detail = ref(null), loading = ref(true), error = ref('')
const tab = ref(tabForView(props.initialTab)), visited = reactive(new Set([tab.value]))
const allReports = ref(false), compareOpen = ref(false), downloading = ref(false)
const results = reactive({ loading: false, error: '', report: null })
const buyers = reactive({ loading: false, error: '', survey: null, loaded: false })
const activity = reactive({ loading: false, loaded: false, timeline: [], stats: [] })
const verdict = ref(['yes', 'maybe', 'no'].includes(props.initialVerdict) ? props.initialVerdict : ''), shown = ref(8)
const verdictWord = { yes: 'Would buy', maybe: 'Maybe', no: 'Would not buy' }
const spendHint = 'Uses model calls. You see the cost and approve it first.'

const stats = computed(() => runCardStats(detail.value))
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
async function loadBuyers() {
  buyers.error = ''
  if (!(detail.value?.files || []).includes('survey.json')) { buyers.loaded = true; return }
  buyers.loading = true
  try { buyers.survey = await api(`/api/runs/${enc()}/files/survey.json`); buyers.loaded = true }
  catch (e) { buyers.error = e.message } finally { buyers.loading = false }
}
async function loadActivity() {
  const files = new Set(detail.value?.files || [])
  activity.loading = true
  const read = (f) => (files.has(f) ? api(`/api/runs/${enc()}/files/${f}`).catch(() => null) : Promise.resolve(null))
  const [timeline, stats] = await Promise.all([read('timeline.json'), read('agent_stats.json')])
  activity.timeline = Array.isArray(timeline) ? timeline : []
  activity.stats = stats || []
  activity.loaded = true; activity.loading = false
}
// each tab reads its own files the first time it opens
function openTab(id) {
  if (!detail.value) return
  if (id === 'results' && !results.report && !results.loading) loadResults()
  if (id === 'thinking' && !buyers.loaded && !buyers.loading) loadBuyers()
  if (id === 'activity' && !activity.loaded && !activity.loading) loadActivity()
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
  const next = moveTab(RUN_CARD_TABS, tab.value, event.key)
  if (!next) return
  event.preventDefault()
  select(next)
  nextTick(() => document.getElementById(`${uid}-tab-${next}`)?.focus())
}
watch(() => props.name, () => { results.report = null; buyers.survey = null; buyers.loaded = false; activity.loaded = false; allReports.value = false; load() }, { immediate: true })

const counts = computed(() => verdictCounts(buyers.survey))
const verdictFilters = computed(() => [
  { id: '', label: 'All', count: counts.value.yes + counts.value.maybe + counts.value.no },
  { id: 'yes', label: 'Would buy', count: counts.value.yes },
  { id: 'maybe', label: 'Maybe', count: counts.value.maybe },
  { id: 'no', label: 'Would not', count: counts.value.no }
])
const responses = computed(() => buyerResponses(buyers.survey, verdict.value))
const rounds = computed(() => activityRounds(activity.timeline))
const actors = computed(() => topActors(activity.stats))
const mix = computed(() => actionMix(activity.timeline))

function act(type) { emit('action', { type, run: props.name, title: stats.value.title || props.name }) }
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
.rcc-filter { display: flex; gap: 6px; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin-bottom: 12px; }
.rcc-filter::-webkit-scrollbar { display: none; }
.rcc-filter button { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 5px 11px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--muted); font: inherit; font-size: 12px; cursor: pointer; }
.rcc-filter button span { font-variant-numeric: tabular-nums; color: var(--muted); font-size: 11px; }
.rcc-filter button[aria-pressed='true'] { border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); background: var(--accent-2); color: var(--text); font-weight: 550; }
.rcc-responses { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.rcc-responses li { padding: 11px 13px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); font-size: 12.5px; line-height: 1.6; min-width: 0; }
.rcc-responses header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.rcc-responses header b { font-weight: 600; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rcc-said { flex-shrink: 0; font-size: 10.5px; font-weight: 600; padding: 0 8px; border-radius: 999px; border: 1px solid var(--line); line-height: 1.8; }
.rcc-said.yes { color: var(--yes); border-color: color-mix(in srgb, var(--yes) 45%, var(--line)); }
.rcc-said.maybe { color: var(--maybe); border-color: color-mix(in srgb, var(--maybe) 50%, var(--line)); }
.rcc-said.no { color: var(--no); border-color: color-mix(in srgb, var(--no) 45%, var(--line)); }
.rcc-quote { margin: 6px 0 0; font-size: 13px; overflow-wrap: anywhere; }
.rcc-why { margin: 4px 0 0; color: var(--muted); overflow-wrap: anywhere; }
.rcc-why span { color: var(--text); font-weight: 550; }
.rcc-show-more { margin-top: 10px; }
.rcc-mix { list-style: none; margin: 0 0 14px; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.rcc-mix li { padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; font-size: 12px; color: var(--muted); }
.rcc-mix b { color: var(--text); font-weight: 650; font-variant-numeric: tabular-nums; }
.rcc-rounds h4, .rcc-actors h4 { margin: 0 0 8px; font-size: 12.5px; font-weight: 600; }
.rcc-rounds ol, .rcc-actors ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.rcc-rounds li { display: grid; grid-template-columns: 70px minmax(0, 1fr) 56px; align-items: center; gap: 10px; font-size: 12px; font-variant-numeric: tabular-nums; }
.rcc-rounds li > span:first-child { color: var(--muted); }
.rcc-rounds li > b { text-align: right; font-weight: 600; }
.rcc-bar { height: 6px; border-radius: 999px; background: var(--panel-2); overflow: hidden; }
.rcc-bar i { display: block; height: 100%; border-radius: inherit; background: var(--data); }
.rcc-actors { margin-top: 16px; }
.rcc-actors li { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-top: 1px solid var(--line); font-size: 12px; }
.rcc-actors li:first-child { border-top: 0; }
.rcc-actors b { font-weight: 550; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rcc-actors span { color: var(--muted); text-align: right; flex-shrink: 0; max-width: 60%; }
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
  .rcc-rounds li { grid-template-columns: 62px minmax(0, 1fr) 48px; }
}
</style>
