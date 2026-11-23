<template>
  <div class="ws-run" :class="{ 'wide-visual': tab !== 'results' }">
      <div class="ws-tabs workspace-modal-tabs" role="tablist" aria-label="Run visualizations" @keydown="onTabKey">
        <button v-for="t in tabs" :id="`${tabId}-${t.id}`" :key="t.id" role="tab" :tabindex="tab === t.id ? 0 : -1" :aria-controls="`${tabId}-panel`" :aria-selected="tab === t.id" @click="tab = t.id">
          {{ t.label }}
        </button>
      </div>
    <div v-show="tab === 'results'" :id="tab === 'results' ? `${tabId}-panel` : undefined" role="tabpanel" :aria-labelledby="`${tabId}-results`" tabindex="0" class="ws-run-main" ref="scroller">
      <p v-if="loading" class="ws-empty">Loading the run…</p>
      <template v-else-if="detail">
        <p v-if="error" class="ws-error" role="alert">{{ error }}</p>
        <div class="ws-title">
          <h2>{{ detail.title }}</h2>
          <p class="ws-run-context">{{ decision ? `Saved decision: ${decision.replaceAll('_', ' ')}` : 'Saved research' }} · Results from simulated participants</p>
        </div>
        <p v-if="detail.summary?.decision?.summary" class="ws-note" style="font-size: 13px">
          {{ detail.summary.decision.summary }}
        </p>

        <div class="ws-steps">
          <details v-for="step in steps" :key="step.id" class="ws-step" :open="step.open">
            <summary>
              {{ step.title }} <time v-if="step.time">{{ step.time }}</time>
            </summary>
            <div class="ws-step-body">
              <div v-if="step.chart" class="ws-box">
                <h3>{{ step.chartTitle }}</h3>
                <EChart :option="step.chart" :height="step.height || 260" :label="step.chartTitle" :theme="theme" />
              </div>
              <p v-if="step.text" class="ws-note" style="font-size: 13px">{{ step.text }}</p>
              <div v-for="q in step.quotes || []" :key="q.text" class="ws-quote">
                “{{ q.text }}”<small>{{ q.who }}</small>
              </div>
            </div>
          </details>
        </div>

        <ArtifactExplorer :name="name" :files="detail.files || []" :theme="theme" />

        <details class="ws-run-questions"><summary>Ask about this experiment</summary>
        <div class="ws-chat" aria-live="polite">
          <div v-for="(m, i) in messages" :key="i" class="ws-msg" :class="{ me: m.role === 'user' }">
            <small>{{ m.role === 'user' ? 'You' : m.who || 'MarketMirror' }}</small>{{ m.text }}
            <div v-if="m.chartKey && chartFor(m)" class="ws-box" style="margin-top: 10px">
              <EChart :option="chartFor(m)" :height="240" :label="m.caption" :caption="m.caption" :theme="theme" />
            </div>
            <ChatArtifact v-if="m.artifact" :name="name" :file="m.artifact.file" :path="m.artifact.path || []" :title="m.artifact.title" :files="detail.files || []" :theme="theme" />
            <div v-if="m.reportFiles" class="ws-chat-report-links"><button v-for="file in m.reportFiles" :key="file" class="ws-chip" @click="openReport(file)">{{ reportTitle(file) }}</button></div>
          </div>
          <p v-if="busy" class="ws-note">Thinking…</p>
        </div>

        <div class="ws-dock">
          <div v-if="showSuggest" class="ws-suggest" role="listbox" aria-label="Suggested questions">
            <p>↑ ↓ to move · Enter to ask · Esc to close</p>
            <button
              v-for="(s, i) in suggestions"
              :key="s"
              role="option"
              :aria-selected="i === active"
              @mousedown.prevent="ask(s)"
            >
              {{ s }}
            </button>
          </div>
          <div class="ws-composer">
            <label class="sr-only" for="ws-ask">Ask about this run</label>
            <textarea
              id="ws-ask"
              v-model="draft"
              rows="2"
              :placeholder="placeholder"
              @focus="focused = true"
              @blur="focused = false"
              @keydown="onKey"
            ></textarea>
            <div class="ws-composer-row">
              <button
                v-for="m in modes"
                :key="m.id"
                class="ws-chip"
                :aria-pressed="mode === m.id"
                :title="m.title"
                @click="mode = m.id"
              >
                {{ m.label }}
              </button>
              <select v-if="mode === 'person'" v-model.number="personId" class="ws-chip" aria-label="Simulated person">
                <option v-for="p in people" :key="p.agent_id" :value="p.agent_id">
                  {{ p.name }} · {{ p.segment || p.country }}
                </option>
              </select>
              <label class="ws-chat-report-select">Visualize report
                <select :value="''" aria-label="Visualize a saved report in chat" @change="openReport($event.target.value)"><option value="" disabled>Choose a saved file</option><option v-for="file in detail.files || []" :key="file" :value="file">{{ reportTitle(file) }}</option></select>
              </label>
              <button class="ws-send" :disabled="!draft.trim() || busy" aria-label="Send" @click="ask(draft)">↑</button>
            </div>
            <p class="ws-note">{{ modeNote }}</p>
          </div>
        </div>
        </details>
      </template>
      <p v-else class="ws-empty">{{ error || 'Run not found.' }}</p>
    </div>

    <aside v-show="tab !== 'results'" class="ws-run-side" aria-label="Run visuals">
      <div v-if="tab === 'market'" class="ws-audience-toolbar"><span>Explore the simulated audience</span><button class="ws-btn" @click="tab = 'results'">Back to results</button></div>

      <div :id="tab !== 'results' ? `${tabId}-panel` : undefined" class="ws-tabpanel" role="tabpanel" :aria-labelledby="`${tabId}-${tab}`" tabindex="0">
        <template v-if="tab === 'thinking'">
          <p class="ws-note" style="margin-bottom: 6px">
            What the simulated people said and thought, from the saved answers. Written by a model playing each person.
          </p>
          <WorkspacePager v-model:page="thoughtPage" :total="thoughts.length" label="thoughts and responses" />
          <div v-for="(t, i) in pagedThoughts" :key="i" class="ws-thought">
            <header>
              <span class="ws-dot" :style="{ background: t.color }"></span>{{ t.who }} · {{ t.where }}
            </header>
            {{ t.text }}
          </div>
          <WorkspacePager v-if="thoughts.length > 30" v-model:page="thoughtPage" :total="thoughts.length" label="thoughts and responses" />
          <p v-if="!thoughts.length" class="ws-empty">No saved thoughts in this run.</p>
        </template>
        <template v-else-if="tab === 'market'">
          <PersonaScene :people="people" :activity="agentRows" :timeline="activityTimeline" :responses="survey?.responses || []" :theme="theme" :status="runStatus" :checked-at="lastChecked" />
        </template>
        <template v-else-if="tab === 'activity'">
          <p class="ws-note">Recorded actions and analyst contributions from this run.</p>
          <EChart v-if="timelineChart" :option="timelineChart" :height="230" label="Recorded actions by round" :theme="theme" />
          <WorkspacePager v-model:page="analystPage" :total="analystRows.length" label="analysts" />
          <div v-for="a in pagedAnalysts" :key="a.id || a.lens" class="ws-thought"><header>{{ a.lens || a.id }} <span class="pill">{{ a.error ? 'Failed' : 'Saved' }}</span></header><p>{{ a.error || a.result?.summary || a.result?.verdict || 'Analysis saved in the analyst panel report.' }}</p></div>
          <WorkspacePager v-model:page="agentPage" :total="agentRows.length" label="agents" />
          <div v-for="a in pagedAgents" :key="a.agent_id" class="ws-thought"><header>{{ a.agent_name || `Agent ${a.agent_id}` }}</header>{{ a.total_actions != null ? `${a.total_actions} recorded actions` : 'Action count not recorded' }}<p class="ws-note">{{ Object.entries(a.action_types || {}).map(([k, v]) => `${k.toLowerCase().replaceAll('_', ' ')}: ${v}`).join(' · ') }}</p></div>
          <WorkspacePager v-if="agentRows.length > 30" v-model:page="agentPage" :total="agentRows.length" label="agents" />
          <p v-if="!agentRows.length && !analystRows.length && !timelineChart" class="ws-empty">No agent activity was saved in this run. Saved results do not indicate that agents are currently running.</p>
        </template>
        <template v-else>
          <WorkspacePager v-model:page="postPage" :total="posts.length" label="social posts" />
          <div v-for="post in pagedPosts" :key="post.key" class="ws-thought">
            <header>{{ post.who }} · {{ post.platform }}<template v-if="post.score != null"> · Score {{ post.score }}</template></header>
            <p v-if="post.quote" class="ws-post-quote">{{ post.quote }}</p>
            <p v-if="post.originalPostId != null" class="ws-note">Original post #{{ post.originalPostId }}</p>
            <p v-if="post.text">{{ post.text }}</p>
            <details v-if="post.comments.length" class="ws-post-replies"><summary>{{ post.comments.length }} saved replies</summary><ResultTree :value="post.comments" :theme="theme" /></details>
          </div>
          <WorkspacePager v-if="posts.length > 30" v-model:page="postPage" :total="posts.length" label="social posts" />
          <p v-if="!posts.length" class="ws-empty">No social posts saved in this run.</p>
        </template>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onMounted, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import EChart from './EChart.vue'
import ArtifactExplorer from './ArtifactExplorer.vue'
import ChatArtifact from './ChatArtifact.vue'
import WorkspacePager from './WorkspacePager.vue'
import ResultTree from './ResultTree.vue'
import { neededRawPosts, socialPosts } from '../../workspace/socialPosts.js'
import { funnelRows, pricingText, reportTitle, savedReportFor } from '../../workspace/resultRouting.js'
const PersonaScene = defineAsyncComponent(() => import('./PersonaScene.vue'))
import { api, download, openHtml } from '../../workspace/api.js'
import {
  creativesOption, intentOption, localAnswer, objectionsOption, palette, peopleOption, segmentsOption
} from '../../workspace/charts.js'

const props = defineProps({ name: { type: String, required: true }, theme: { type: String, default: 'light' } })

const detail = ref(null), loading = ref(true), error = ref('')
const survey = ref(null), feed = ref(null), graph = ref(null), config = ref(null), story = ref(null), stream = ref(null)
const extra = ref({}), rawPosts = ref({})
const thoughtPage = ref(0), postPage = ref(0), analystPage = ref(0), agentPage = ref(0)
const tab = ref('results'), tabId = useId(), expandedAudience = ref(false)
watch(tab, value => { if (value !== 'market') expandedAudience.value = false })
const tabs = [{ id: 'results', label: 'Results' }, { id: 'market', label: 'Audience & world' }, { id: 'thinking', label: 'Buyer responses' }, { id: 'activity', label: 'Activity' }, { id: 'feed', label: 'Social feed' }]
const route = useRoute()
watch(() => route.query.view, value => {
  if (tabs.some(item => item.id === value)) {
    tab.value = value
    expandedAudience.value = value === 'market'
  }
}, { immediate: true })
const messages = ref([]), draft = ref(''), busy = ref(false), focused = ref(false), active = ref(0)
const mode = ref('run'), personId = ref(null), scroller = ref(null)
const modes = [
  { id: 'run', label: 'From the results', title: 'Answers from the saved files; no model call' },
  { id: 'person', label: 'Ask a person', title: 'One model call to your provider' },
  { id: 'report', label: 'Report agent', title: 'One or more model calls to your provider' }
]

const fmtTime = (iso) => {
  try {
    return new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}
const storeKey = computed(() => `mm-chat-${props.name}`)

let loadTicket = 0, refreshTimer, refreshInFlight = false
const lastChecked = ref('')
async function load(quiet = false) {
  if (quiet && refreshInFlight) return
  const ticket = ++loadTicket, runName = props.name
  refreshInFlight = true
  if (!quiet) loading.value = true
  try {
    const nextDetail = await api(`/api/runs/${encodeURIComponent(runName)}`)
    const has = new Set(nextDetail.files || [])
    const files = ['survey.json', 'feed_test.json', 'graph.json', 'config.json', 'feed_story.json', 'thought_stream.json', 'pitch.json', 'analyst_panel.json', 'timeline.json', 'agent_stats.json']
    const nextFiles = {}, failures = []
    await Promise.all(files.map(async f => {
      if (!has.has(f)) return
      try { nextFiles[f] = await api(`/api/runs/${encodeURIComponent(runName)}/files/${f}`) }
      catch (e) { failures.push(`${f}: ${e.message}`) }
    }))
    const requiredRaw = neededRawPosts(nextFiles['feed_story.json'] ?? (quiet ? story.value : null), nextDetail.files)
    const nextRaw = {}
    await Promise.all(requiredRaw.map(async platform => {
      const file = `posts_${platform}.json`
      try { nextRaw[platform] = await api(`/api/runs/${encodeURIComponent(runName)}/files/${file}`) }
      catch (e) { failures.push(`${file}: ${e.message}`); if (quiet && rawPosts.value[platform]) nextRaw[platform] = rawPosts.value[platform] }
    }))
    if (ticket !== loadTicket) return
    rawPosts.value = nextRaw
    detail.value = nextDetail
    for (const [file, target] of [['survey.json', survey], ['feed_test.json', feed], ['graph.json', graph], ['config.json', config], ['feed_story.json', story], ['thought_stream.json', stream]]) {
      if (Object.hasOwn(nextFiles, file)) target.value = nextFiles[file]
      else if (!quiet || !has.has(file)) target.value = null
    }
    const extras = { ...(quiet ? extra.value : {}) }
    for (const f of ['pitch.json', 'analyst_panel.json', 'timeline.json', 'agent_stats.json']) {
      if (Object.hasOwn(nextFiles, f)) extras[f] = nextFiles[f]
      else if (!has.has(f)) delete extras[f]
    }
    extra.value = extras
    error.value = failures.length ? `Some saved results could not refresh: ${failures.join('; ')}` : ''
    lastChecked.value = new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    if (!quiet) {
      thoughtPage.value = postPage.value = analystPage.value = agentPage.value = 0
      try { const saved = JSON.parse(localStorage.getItem(storeKey.value) || '[]'); messages.value = Array.isArray(saved) ? saved : [] } catch { messages.value = [] }
      personId.value = people.value[0]?.agent_id ?? null
    }
  } catch (e) {
    if (ticket !== loadTicket) return
    error.value = e.message
    if (!quiet) detail.value = null
  } finally {
    if (ticket === loadTicket) { loading.value = false; refreshInFlight = false }
  }
}
watch(() => props.name, () => load(), { immediate: true })
function refreshVisibleRun() { if (!document.hidden && detail.value) load(true) }
onMounted(() => {
  refreshTimer = setInterval(refreshVisibleRun, 8000)
  document.addEventListener('visibilitychange', refreshVisibleRun)
})
onBeforeUnmount(() => {
  loadTicket++
  clearInterval(refreshTimer)
  document.removeEventListener('visibilitychange', refreshVisibleRun)
})
watch(messages, (v) => {
  try {
    localStorage.setItem(storeKey.value, JSON.stringify(v.slice(-60)))
  } catch {
    /* private mode: chat still works for this page */
  }
}, { deep: true })

const mk = computed(() => detail.value?.summary?.marketing || null)
const index = computed(() => config.value?.persona_index || [])
const people = computed(() => index.value.filter((r) => (r.kind || 'persona') === 'persona'))
const decision = computed(() => detail.value?.summary?.decision?.decision || detail.value?.decision || '')
const decisionClass = computed(() => decision.value.toLowerCase().replace(' ', '-'))
const runData = computed(() => ({ summary: detail.value?.summary, feed: feed.value, index: index.value }))

function barChart(rows, labelKey, metric, metricLabel) {
  if (!Array.isArray(rows)) return null
  rows = rows.filter((r) => r && Number.isFinite(r[metric]))
  if (!rows.length) return null
  const p = palette()
  return { tooltip: { trigger: 'axis', confine: true }, grid: { left: 8, right: 24, top: 14, bottom: 44, containLabel: true }, xAxis: { type: 'value', name: metricLabel, nameLocation: 'middle', nameGap: 30, nameTextStyle: { color: p.muted }, axisLabel: { color: p.muted }, splitLine: { lineStyle: { color: p.line } } }, yAxis: { type: 'category', data: rows.map((r, i) => r[labelKey] ?? r.segment ?? r.country ?? `Round ${r.round_num ?? i + 1}`).reverse(), axisLabel: { color: p.text, width: 155, overflow: 'truncate' } }, series: [{ name: metricLabel, type: 'bar', data: rows.map((r) => r[metric]).reverse(), itemStyle: { color: p.accent, borderRadius: [0, 4, 4, 0] }, barMaxWidth: 18 }] }
}
function pricingChart(pricing) {
  const rows = pricing?.by_segment
  if (!Array.isArray(rows) || !rows.some(r => Number.isFinite(r.cheap))) return null
  const p = palette(), currency = survey.value?.currency || 'saved currency units'
  return { tooltip: { trigger: 'axis', confine: true }, legend: { textStyle: { color: p.muted } }, grid: { left: 8, right: 24, top: 40, bottom: 44, containLabel: true }, xAxis: { type: 'value', name: currency, nameLocation: 'middle', nameGap: 30, axisLabel: { color: p.muted }, splitLine: { lineStyle: { color: p.line } } }, yAxis: { type: 'category', data: rows.map(r => r.key).reverse(), axisLabel: { color: p.text, width: 145, overflow: 'truncate' } }, series: [['cheap', 'Cheap'], ['expensive', 'Expensive'], ['too_expensive', 'Too expensive']].map(([key, name], i) => ({ name, type: 'bar', data: rows.map(r => Number.isFinite(r[key]) ? Number(r[key].toFixed(2)) : null).reverse(), itemStyle: { color: p.series[i], borderRadius: [0, 3, 3, 0] }, barMaxWidth: 12 })) }
}
const agentRows = computed(() => { const data = extra.value['agent_stats.json']; return Array.isArray(data) ? data : Array.isArray(data?.agents) ? data.agents : [] })
const analystRows = computed(() => Array.isArray(extra.value['analyst_panel.json']?.analysts) ? extra.value['analyst_panel.json'].analysts : [])
const timelineChart = computed(() => { props.theme; return barChart(extra.value['timeline.json'] || [], 'round', 'total_actions', 'Recorded actions') })

const steps = computed(() => {
  if (!detail.value) return []
  const m = detail.value.manifest || {}
  const t = props.theme // eslint-disable-line no-unused-vars -- options read theme colours
  const out = [{
    id: 'people', title: `${people.value.length || detail.value.people || 0} simulated people created`,
    time: fmtTime(m.started_at), chart: peopleOption(index.value), chartTitle: 'People by country', height: 260, open: true
  }]
  if (feed.value) out.push({ id: 'feed', title: 'Ads scrolled in realistic feeds', chart: creativesOption(feed.value), chartTitle: 'Expected click-through per ad', open: true })
  if (mk.value) {
    out.push({ id: 'intent', title: 'Buyer survey answered', chart: intentOption(mk.value), chartTitle: 'Purchase intent', open: true })
    const seg = segmentsOption(mk.value)
    if (seg) out.push({ id: 'segments', title: 'Which audience to target', chart: seg, chartTitle: 'Would convert by segment', height: Math.max(260, 60 + 28 * Math.min(12, mk.value.by_segment.length)), text: mk.value.segment_shrink?.note, open: true })
    const obj = objectionsOption(mk.value)
    if (obj) out.push({ id: 'objections', title: 'Why people said no', chart: obj, chartTitle: 'Objections', quotes: (mk.value.objections || []).slice(0, 2).flatMap((o) => (o.examples || []).slice(0, 1).map((ex) => ({ text: ex.text, who: `${ex.name} · ${ex.segment}` }))), open: false })
  }
  for (const [key, title, field] of [['by_country', 'Purchase intent by country', 'key'], ['by_community', 'Purchase intent by community', 'key'], ['by_age', 'Purchase intent by age', 'key']]) {
    const rows = mk.value?.[key] || []
    const chart = barChart(rows, field, 'convert_yes', 'Would convert (%)')
    if (chart) out.push({ id: key, title, chart, chartTitle: title, open: false })
  }
  const funnel = barChart(funnelRows(mk.value?.funnel), 'label', 'n', 'Simulated people (count)')
  if (funnel) out.push({ id: 'funnel', title: 'Simulated buyer funnel', chart: funnel, chartTitle: 'Simulated buyer funnel', open: false })
  const pricing = mk.value?.pricing
  if (pricing) out.push({ id: 'pricing', title: 'What buyers would pay', text: pricingText(pricing, survey.value?.currency), chart: pricingChart(pricing), chartTitle: 'Median price thresholds by segment', open: false })
  const pitch = extra.value['pitch.json']
  if (pitch) out.push({ id: 'pitch', title: 'Sales pitch rehearsal', chart: barChart(pitch.by_segment || [], 'segment', 'yes', 'Yes (%)'), chartTitle: 'Pitch acceptance by audience', text: `${pitch.answered ?? 'Not recorded'} simulated answers. Open the pitch report below for objections, replies and fixes.`, open: false })
  return out
})

const activityTimeline = computed(() => Array.isArray(extra.value['timeline.json']) ? extra.value['timeline.json'] : [])
const runStatus = computed(() => String(detail.value?.status || detail.value?.summary?.runner_status || detail.value?.manifest?.status || ''))

const thoughts = computed(() => {
  const p = palette()
  const segs = [...new Set(people.value.map((r) => r.segment))]
  const color = (seg) => p.series[Math.max(0, segs.indexOf(seg)) % p.series.length]
  const byId = Object.fromEntries(index.value.map((r) => [r.agent_id, r]))
  const out = []
  for (const t of (Array.isArray(stream.value) ? stream.value : stream.value?.thoughts || stream.value?.items || [])) {
    const who = byId[t.agent_id] || {}
    out.push({ who: who.name || t.name || `Person ${t.agent_id}`, where: t.source || 'thought', text: t.text || t.thought, color: color(who.segment) })
  }
  for (const r of survey.value?.responses || []) {
    const a = r.answer || {}
    const text = a.quote || a.main_objection
    if (!text) continue
    const who = byId[r.agent_id] || {}
    out.push({ who: r.name || who.name, where: `survey · ${a.would_convert || '–'}`, text, color: color(who.segment) })
  }
  for (const s of feed.value?.sessions || []) {
    if (s.ad?.thought) out.push({ who: s.name, where: `scrolling ${s.platform} · ${s.creative_id}`, text: s.ad.thought, color: color(s.segment) })
  }
  return out.filter(item => item.text)
})

const posts = computed(() => socialPosts(story.value, rawPosts.value, index.value))
const pageSize = 30
const pagedThoughts = computed(() => thoughts.value.slice(thoughtPage.value * pageSize, (thoughtPage.value + 1) * pageSize))
const pagedPosts = computed(() => posts.value.slice(postPage.value * pageSize, (postPage.value + 1) * pageSize))
const pagedAnalysts = computed(() => analystRows.value.slice(analystPage.value * pageSize, (analystPage.value + 1) * pageSize))
const pagedAgents = computed(() => agentRows.value.slice(agentPage.value * pageSize, (agentPage.value + 1) * pageSize))
watch(() => [thoughts.value.length, posts.value.length, analystRows.value.length, agentRows.value.length], lengths => {
  for (const [i, page] of [thoughtPage, postPage, analystPage, agentPage].entries()) page.value = Math.min(page.value, Math.max(0, Math.ceil(lengths[i] / pageSize) - 1))
})

const suggestions = computed(() => {
  const base = ['Which audience should we target?', 'Why did people say no?', 'Show pricing', 'Show analyst panel', 'Show all reports']
  const q = draft.value.trim().toLowerCase()
  return (q ? base.filter((s) => s.toLowerCase().includes(q)) : base).slice(0, 5)
})
const showSuggest = computed(() => focused.value && mode.value === 'run' && suggestions.value.length > 0 && !busy.value)
const placeholder = computed(() => ({ run: 'Ask about results, or show pricing, analyst panel, action plan…', person: 'Ask this simulated person anything…', report: 'Ask the report agent about this run…' })[mode.value])
const modeNote = computed(() => ({
  run: 'Explore saved results and visualize any report here. No model call.',
  person: 'Sends one model call to your configured provider. The reply is written by a model playing this invented person.',
  report: 'Sends one or more model calls to your configured provider. Needs the simulation on this backend.'
})[mode.value])

function chartFor(m) {
  const map = { segments: segmentsOption, objections: objectionsOption, intent: intentOption, decision: intentOption }
  if (m.chartKey === 'creatives') return creativesOption(feed.value)
  if (m.chartKey === 'people') return peopleOption(index.value)
  if (m.chartKey === 'pricing') return pricingChart(mk.value?.pricing)
  if (m.chartKey === 'funnel') return barChart(funnelRows(mk.value?.funnel), 'label', 'n', 'Simulated people (count)')
  if (['by_country', 'by_community', 'by_age'].includes(m.chartKey)) return barChart(mk.value?.[m.chartKey], 'key', 'convert_yes', 'Would convert (%)')
  return map[m.chartKey] ? map[m.chartKey](mk.value) : null
}

function onTabKey(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const index = tabs.findIndex(t => t.id === tab.value)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length
  tab.value = tabs[next].id
  nextTick(() => document.getElementById(`${tabId}-${tab.value}`)?.focus())
}
function openReport(file) {
  if (!file || busy.value || !(detail.value?.files || []).includes(file)) return
  mode.value = 'run'
  ask(`Show ${file}`)
}

function onKey(e) {
  if (showSuggest.value && ['ArrowDown', 'ArrowUp'].includes(e.key)) {
    e.preventDefault()
    const n = suggestions.value.length
    active.value = (active.value + (e.key === 'ArrowDown' ? 1 : n - 1)) % n
  } else if (e.key === 'Escape') {
    focused.value = false
  } else if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    ask(showSuggest.value && !draft.value.trim() ? suggestions.value[active.value] : draft.value)
  }
}

async function ask(text) {
  text = (text || '').trim()
  if (!text || busy.value) return
  draft.value = ''
  messages.value.push({ role: 'user', text })
  busy.value = true
  try {
    if (mode.value === 'run') {
      const request = text.toLowerCase()
      if (/\b(all reports|all files|everything|list reports|list files)\b/.test(request)) {
        const files = detail.value.files || []
        messages.value.push({ role: 'assistant', text: `${files.length} saved reports and evidence files. Choose one to read and visualize it in this chat.`, reportFiles: files })
        return
      }
      const artifact = savedReportFor(text, detail.value.files, detail.value.summary)
      if (artifact) {
        const key = artifact.path?.at(-1)
        messages.value.push({ role: 'assistant', text: `${artifact.title}, from the saved run.`, artifact, chartKey: ['pricing', 'funnel', 'by_country', 'by_community', 'by_age'].includes(key) ? key : undefined, caption: artifact.title })
        return
      }
      const local = localAnswer(text, runData.value)
      messages.value.push(local
        ? { role: 'assistant', text: local.text, chartKey: local.chartKey, caption: local.caption }
        : { role: 'assistant', text: 'I could not match that question to a saved result. Choose any report below to read its full contents here, or use the report agent for a model-generated answer.', reportFiles: detail.value.files || [] })
    } else if (mode.value === 'person') {
      const sid = detail.value.simulation_id
      const history = messages.value.filter((m) => m.who && m.agent === personId.value).slice(-6).map((m) => ({ role: m.role === 'user' ? 'user' : 'person', text: m.text }))
      if (personId.value == null || !sid) throw new Error('This run has no available simulated person to ask.')
      const r = await api('/api/simulation/ask', { method: 'POST', body: { simulation_id: sid, agent_id: personId.value, message: text, history } })
      messages.value.push({ role: 'assistant', who: `${r.name} (simulated, ${r.segment || 'no segment'})`, agent: personId.value, text: r.reply })
    } else {
      const sid = detail.value.simulation_id
      const chat_history = messages.value.slice(-8).map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }))
      const r = await api('/api/report/chat', { method: 'POST', body: { simulation_id: sid, message: text, chat_history } })
      messages.value.push({ role: 'assistant', who: 'Report agent', text: r.response || r.answer || JSON.stringify(r) })
    }
  } catch (e) {
    messages.value.push({ role: 'assistant', text: `Could not answer: ${e.message}` })
  } finally {
    busy.value = false
    active.value = 0
    await nextTick()
    scroller.value && scroller.value.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  }
}

async function fetchFile(f) {
  try {
    await download(props.name, f)
  } catch (e) {
    error.value = e.message
  }
}
async function openDashboard() {
  try {
    await openHtml(props.name, 'dashboard.html')
  } catch (e) {
    error.value = e.message
  }
}
</script>

<style scoped>
.ws-run{display:flex!important;flex-direction:column;height:calc(100dvh - 90px);min-height:0;overflow:hidden}.ws-run>.ws-tabs{flex-shrink:0;justify-content:flex-start;gap:6px;padding:11px 22px;background:var(--panel);border-bottom:1px solid var(--line);overflow-x:auto}.ws-run>.ws-tabs button{font-size:12px;white-space:nowrap;padding:9px 13px}.ws-run>.ws-tabs button[aria-selected=true]{background:var(--accent-2);color:var(--text)}.ws-run>.ws-run-main{display:block;flex:1;min-height:0;max-height:none;overflow-y:auto;padding:26px 30px 35px;scroll-padding-bottom:30px}.ws-run>.ws-run-side{display:flex;flex:1;min-height:0;max-height:none;border:0;overflow:hidden}.ws-run .ws-tabpanel{padding:22px 26px;min-height:0;overflow:auto}.ws-run .ws-title{display:block;margin-bottom:12px}.ws-run .ws-title h2{font-size:21px;line-height:1.5;font-weight:550;letter-spacing:-.3px;max-width:1000px}.ws-run-context{font-size:11px;color:var(--muted);line-height:1.7;margin-top:8px}.ws-run .ws-steps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:24px;align-items:start}.ws-run .ws-step{margin:0;border:1px solid var(--line);border-radius:13px;background:var(--panel);min-width:0;overflow:hidden}.ws-run .ws-step>summary{font-size:13px;font-weight:550;line-height:1.6;padding:16px}.ws-run .ws-step-body{padding:0 16px 16px}.ws-run .ws-step .ws-box{border:0;box-shadow:none;margin:0;padding:0;background:transparent}.ws-run .ws-step h3{font-size:11px;font-weight:500;color:var(--muted);margin-bottom:10px}.ws-run .ws-step time{display:none}.ws-run-questions{margin-top:28px;padding-top:20px;border-top:1px solid var(--line)}.ws-run-questions>summary{font-size:14px;font-weight:550;cursor:pointer}.ws-run-questions .ws-dock{position:static;padding-bottom:0;background:none;margin-top:15px}.ws-run-questions .ws-composer{margin-top:12px}.ws-run-questions .ws-note{font-size:10px;line-height:1.7}.ws-run.wide-visual :deep(.persona-viewport){height:clamp(330px,50vh,620px)}@media(max-width:760px){.ws-run{height:calc(100dvh - 80px)}.ws-run>.ws-run-main{padding:21px 16px 30px}.ws-run .ws-steps{grid-template-columns:1fr;gap:11px}.ws-run>.ws-tabs{padding:9px}.ws-run>.ws-tabs button{padding:8px 10px;font-size:11px}.ws-run .ws-tabpanel{padding:18px 15px}.ws-run .ws-title h2{font-size:18px}}
.ws-post-quote{padding-left:10px;border-left:2px solid var(--accent);margin-bottom:10px}.ws-post-replies{margin-top:12px}.ws-post-replies summary{cursor:pointer;font-size:12px;color:var(--muted)}.ws-audience-toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}.ws-run.wide-visual{grid-template-columns:minmax(0,1fr)}.ws-run.wide-visual>.ws-run-main{display:none}.ws-run.wide-visual>.ws-run-side{border-left:0}.ws-run.wide-visual :deep(.persona-viewport){height:min(60vh,580px)}.ws-chat-report-links{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.ws-chat-report-select{display:flex;gap:6px;align-items:center;font-size:11px;color:var(--muted);max-width:100%}.ws-chat-report-select select{max-width:180px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--text);padding:5px;font-size:12px}
</style>
