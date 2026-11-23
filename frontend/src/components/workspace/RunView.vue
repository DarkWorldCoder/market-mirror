<template>
  <div class="ws-run">
    <div ref="scroller" class="ws-run-main">
      <p v-if="loading" class="ws-empty" role="status">Loading the run…</p>
      <template v-else-if="detail">
        <div class="ws-title">
          <h1>{{ detail.title }}</h1>
          <span v-if="decision" class="pill" :class="decisionClass">{{ decision.toUpperCase() }}</span>
          <span class="pill sim">Simulated</span>
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
              <div v-if="step.files" class="ws-files">
                <button v-for="f in step.files" :key="f" type="button" class="ws-file" @click="fetchFile(f)">
                  <i>{{ f.split('.').pop().toUpperCase() }}</i>{{ f }} <span aria-hidden="true">↓</span>
                </button>
                <button v-if="detail.has_dashboard" type="button" class="ws-file" @click="openDashboard">
                  <i>HTML</i>Full dashboard <span aria-hidden="true">↗</span>
                </button>
              </div>
              <div v-if="step.chart" class="ws-box">
                <h4>{{ step.chartTitle }} <small>simulated</small></h4>
                <EChart :option="step.chart" :height="step.height || 260" :label="step.chartTitle" :theme="theme" />
              </div>
              <p v-if="step.text" class="ws-note" style="font-size: 13px">{{ step.text }}</p>
              <div v-for="q in step.quotes || []" :key="q.text" class="ws-quote">
                “{{ q.text }}”<small>{{ q.who }}</small>
              </div>
            </div>
          </details>
        </div>

        <div class="ws-chat" role="log" aria-live="polite" aria-label="Chat about this run">
          <div v-for="(m, i) in messages" :key="i" class="ws-msg" :class="{ me: m.role === 'user' }">
            <small>
              {{ m.role === 'user' ? `You → ${agentById(m.agent).label}` : m.who || 'MarketMirror' }}
              <span v-if="m.role !== 'user' && m.simulated" class="pill sim xs">Simulated</span>
            </small>
            <span class="ws-msg-text">{{ m.text }}</span>
            <div v-if="m.chartKey && chartFor(m)" class="ws-box" style="margin-top: 10px">
              <EChart :option="chartFor(m)" :height="240" :label="m.caption" :caption="m.caption" :theme="theme" />
            </div>
            <ol v-if="m.transcript" class="ws-transcript">
              <li v-for="(t, j) in m.transcript" :key="j" :class="{ mod: t.speaker === 'Moderator' }">
                <b>{{ t.speaker }}</b><small v-if="t.segment"> · {{ t.segment }}</small>: {{ t.text }}
              </li>
            </ol>
          </div>
          <p v-if="busy" class="ws-note" role="status">{{ busyNote }}</p>
        </div>

        <div class="ws-dock">
          <div v-if="showSuggest" class="ws-suggest" role="listbox" aria-label="Suggested questions">
            <p>↑ ↓ to move · Enter to ask · Esc to close</p>
            <button
              v-for="(s, i) in suggestions"
              :id="`ws-sug-${i}`"
              :key="s"
              type="button"
              role="option"
              :aria-selected="i === active"
              @mousedown.prevent="ask(s)"
            >
              {{ s }}
            </button>
          </div>
          <div class="ws-composer">
            <label class="sr-only" for="ws-ask">Message to {{ agentById(agent).label }}</label>
            <div v-if="attachment" class="ws-attached">
              <span>📎 {{ attachment.name }}</span>
              <button type="button" aria-label="Remove attachment" @click="attachment = null">×</button>
            </div>
            <textarea
              id="ws-ask"
              v-model="draft"
              rows="2"
              :placeholder="placeholder"
              :aria-activedescendant="showSuggest ? `ws-sug-${active}` : undefined"
              @focus="focused = true"
              @blur="focused = false"
              @input="focused = true"
              @keydown="onKey"
            ></textarea>
            <div class="ws-composer-row">
              <button type="button" class="ws-chip icon" aria-label="Attach a text file" @click="fileInput.click()">📎</button>
              <input ref="fileInput" type="file" accept=".txt,.md,.csv,.json" class="sr-only" tabindex="-1" @change="onAttach" />
              <select v-if="agent === 'person'" v-model.number="personId" class="ws-chip" aria-label="Simulated person to talk to">
                <option v-for="p in people" :key="p.agent_id" :value="p.agent_id">
                  {{ p.name }} · {{ p.segment || p.country }}
                </option>
              </select>
              <template v-if="agent === 'focus'">
                <select v-model.number="groupSize" class="ws-chip" aria-label="People in the focus group">
                  <option v-for="n in [3, 4, 5, 6, 8]" :key="n" :value="n">{{ n }} people</option>
                </select>
                <select v-model="groupSegment" class="ws-chip" aria-label="Segment for the focus group">
                  <option value="">Mixed segments</option>
                  <option v-for="s in segments" :key="s" :value="s">{{ s }}</option>
                </select>
              </template>
              <span class="ws-chip ghost" :title="agentById(agent).title">{{ agentById(agent).icon }} {{ agentById(agent).label }}</span>
              <button type="button" class="ws-send" :disabled="!canSend" :aria-label="`Send to ${agentById(agent).label}`" @click="ask(draft)">↑</button>
            </div>
            <p class="ws-note">{{ modeNote }}</p>
          </div>
          <p class="ws-disclaimer">Simulated people, not real buyers. Check decisions with real people before you spend.</p>
        </div>
      </template>
      <p v-else class="ws-empty" role="alert">{{ error || 'Run not found.' }}</p>
    </div>

    <aside class="ws-run-side" aria-label="Run visuals">
      <div class="ws-tabs" role="tablist" aria-label="Visuals" @keydown="onTabKey">
        <button
          v-for="t in tabs"
          :id="`ws-tab-${t.id}`"
          :key="t.id"
          type="button"
          role="tab"
          :aria-selected="tab === t.id"
          :aria-controls="`ws-panel-${t.id}`"
          :tabindex="tab === t.id ? 0 : -1"
          @click="tab = t.id"
        >
          {{ t.label }}<span v-if="t.id === 'status' && isRunning" class="ws-live-dot" aria-label="running"></span>
        </button>
      </div>
      <div :id="`ws-panel-${tab}`" class="ws-tabpanel" role="tabpanel" :aria-labelledby="`ws-tab-${tab}`" tabindex="0">
        <template v-if="tab === 'thinking'">
          <p class="ws-note" style="margin-bottom: 6px">
            What the simulated people thought, said and posted in this run. Written by a model playing each invented person.
          </p>
          <div v-if="thoughtSources.length > 1" class="ws-filter" role="group" aria-label="Filter by where it was written">
            <button type="button" class="ws-chip" :aria-pressed="!thoughtSource" @click="thoughtSource = ''">All {{ thoughts.length }}</button>
            <button v-for="[s, n] in thoughtSources" :key="s" type="button" class="ws-chip" :aria-pressed="thoughtSource === s" @click="thoughtSource = s">
              {{ s }} {{ n }}
            </button>
          </div>
          <div v-for="(t, i) in shownThoughts" :key="i" class="ws-thought">
            <header>
              <span class="ws-dot" :style="{ background: t.color }" aria-hidden="true"></span>{{ t.who }}<template v-if="t.segment"> · {{ t.segment }}</template>
            </header>
            <span class="ws-kind" :class="t.kind">{{ kindLabel[t.kind] || t.kind }}</span> {{ t.text }}
            <small v-if="t.did || t.context">{{ [t.context, t.did].filter(Boolean).join(' → ') }}</small>
          </div>
          <p v-if="!thoughts.length" class="ws-empty">No saved thoughts in this run.</p>
        </template>

        <template v-else-if="tab === 'market'">
          <Market3D v-if="webgl && market3d" :data="market3d" :height="440" :label="market3dLabel" :theme="theme" />
          <EChart v-else-if="market2d" :option="market2d" :height="440" label="Market map of simulated people" :theme="theme" />
          <p class="ws-note">
            {{ webgl ? 'Each small dot is one invented person, coloured by segment and linked to their segment hub (large dot) and to the communities they belong to (pink). Light dots are entities from the market map, linked as the graph links them. Drag to turn, scroll to zoom, hover for names.' : 'This browser has no 3D (WebGL), so the market shows as a map: each dot is one invented person, linked to their segment. Drag and scroll to explore.' }}
            Positions show grouping, not measured distance.
          </p>
          <ul v-if="market3d" class="ws-legend" aria-label="Colours">
            <li v-for="l in market3d.legend" :key="l.name"><span class="ws-dot" :style="{ background: l.color }" aria-hidden="true"></span>{{ l.name }}</li>
          </ul>
          <ul class="ws-legend-list" aria-label="Market summary">
            <li>{{ people.length }} simulated people</li>
            <li>{{ segments.length }} segments</li>
            <li>{{ market3d?.counts.communities ?? communities.length }} communities</li>
            <li>{{ graph?.nodes?.length || 0 }} market map entities</li>
          </ul>
        </template>

        <template v-else-if="tab === 'status'">
          <div v-if="status" class="ws-status">
            <p class="ws-status-head">
              <span class="pill" :class="isRunning ? 'iterate' : status.run?.runner_status === 'failed' ? 'stop' : 'go'">{{ statusLabel }}</span>
              <span class="ws-note">{{ status.live ? 'Live from this backend' : 'Saved status' }}<template v-if="isRunning"> · refreshes every 5 s</template></span>
            </p>
            <div class="ws-progress" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100" :aria-label="`Rounds: ${progress}% done`">
              <span :style="{ width: progress + '%' }"></span>
            </div>
            <dl class="ws-kv">
              <div><dt>Round</dt><dd>{{ status.run?.current_round ?? 0 }} / {{ status.run?.total_rounds ?? 0 }}</dd></div>
              <div><dt>Actions</dt><dd>{{ status.run?.total_actions_count ?? 0 }}</dd></div>
              <div v-if="status.run?.twitter_actions_count !== undefined"><dt>Twitter-style</dt><dd>{{ status.run.twitter_actions_count }}</dd></div>
              <div v-if="status.run?.reddit_actions_count !== undefined"><dt>Reddit-style</dt><dd>{{ status.run.reddit_actions_count }}</dd></div>
              <div v-if="status.started_at || status.run?.started_at"><dt>Started</dt><dd>{{ fmtTime(status.started_at || status.run.started_at) }}</dd></div>
              <div v-if="status.finished_at"><dt>Finished</dt><dd>{{ fmtTime(status.finished_at) }}</dd></div>
            </dl>
            <ol v-if="status.stages?.length" class="ws-stages" aria-label="Stages">
              <li v-for="s in status.stages" :key="s.id" :class="{ done: s.done }">
                <span aria-hidden="true">{{ s.done ? '✓' : '○' }}</span>{{ s.label }}<span class="sr-only">{{ s.done ? ' done' : ' not done' }}</span>
              </li>
            </ol>
            <div v-if="roundsChart" class="ws-box">
              <h4>Actions per round <small>simulated</small></h4>
              <EChart :option="roundsChart" :height="200" label="Actions per round" :theme="theme" />
            </div>
            <p v-if="status.error" class="ws-error" role="alert">{{ status.error }}</p>
          </div>
          <p v-else class="ws-empty">No run status saved.</p>
        </template>

        <template v-else>
          <p class="ws-note" style="margin-bottom: 6px">Posts and replies written by simulated people during the run's social rounds, by platform.</p>
          <div v-if="platforms.length > 1" class="ws-filter" role="group" aria-label="Platform">
            <button v-for="p in platforms" :key="p" type="button" class="ws-chip" :aria-pressed="platform === p" @click="platform = p">
              {{ platformLabel(p) }}
            </button>
          </div>
          <article v-for="(post, i) in posts" :key="i" class="ws-post" :class="{ brand: post.brand }">
            <header>
              <b>{{ post.who }}</b><span v-if="post.brand" class="pill xs">Brand</span>
              <small>{{ [post.segment || post.country, post.round !== undefined ? `round ${post.round}` : ''].filter(Boolean).join(' · ') }}</small>
            </header>
            <p>{{ post.text }}</p>
            <footer>
              <span :aria-label="`${post.likes} likes`">♥ {{ post.likes }}</span>
              <span v-if="post.dislikes" :aria-label="`${post.dislikes} dislikes`">↓ {{ post.dislikes }}</span>
              <span :aria-label="`${post.comments.length} comments`">💬 {{ post.comments.length }}</span>
              <span v-if="post.quotes" :aria-label="`${post.quotes} quotes`">❝ {{ post.quotes }}</span>
            </footer>
            <div v-for="(c, j) in post.comments.slice(0, 2)" :key="j" class="ws-comment">
              <b>{{ c.author?.name || 'Someone' }}</b> {{ c.content }}
            </div>
          </article>
          <p v-if="!posts.length" class="ws-empty">No social posts saved in this run.</p>
        </template>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import EChart from './EChart.vue'
import Market3D from './Market3D.vue'
import { api, download, openHtml } from '../../workspace/api.js'
import { agent, agentById, pending } from '../../workspace/agents.js'
import {
  creativesOption, hasWebGL, intentOption, localAnswer, market2dOption, marketGraph, objectionsOption, palette, peopleOption,
  roundsOption, segmentsOption
} from '../../workspace/charts.js'

const props = defineProps({
  name: { type: String, default: '' },
  sim: { type: String, default: '' },
  theme: { type: String, default: 'dark' },
  provider: { type: Object, default: () => ({}) }
})

const detail = ref(null), loading = ref(true), error = ref('')
const survey = ref(null), feed = ref(null), graph = ref(null), config = ref(null), story = ref(null), harvest = ref(null), status = ref(null)
const tab = ref('thinking')
const tabs = [{ id: 'thinking', label: 'Thinking' }, { id: 'market', label: '3D market' }, { id: 'status', label: 'Live status' }, { id: 'feed', label: 'Social feed' }]
const messages = ref([]), draft = ref(''), busy = ref(false), busyNote = ref(''), focused = ref(false), active = ref(0)
const personId = ref(null), scroller = ref(null), fileInput = ref(null), attachment = ref(null)
const groupSize = ref(5), groupSegment = ref(''), thoughtSource = ref(''), platform = ref('')
let pollTimer = null, alive = true

const key = computed(() => props.name || props.sim)
const enc = encodeURIComponent
const fmtTime = (iso) => {
  try {
    return new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}
const storeKey = computed(() => `mm-chat-${key.value}`)
const sid = computed(() => detail.value?.simulation_id || props.sim)
const onBackend = computed(() => !!detail.value?.simulation_on_backend)

async function loadRun() {
  detail.value = await api(`/api/runs/${enc(props.name)}`)
  const has = new Set(detail.value.files)
  const get = (f, target) => (has.has(f) ? api(`/api/runs/${enc(props.name)}/files/${f}`).then((d) => (target.value = d)).catch(() => null) : null)
  await Promise.all([get('survey.json', survey), get('feed_test.json', feed), get('graph.json', graph), get('config.json', config),
    get('feed_story.json', story),
    api(`/api/runs/${enc(props.name)}/thoughts`).then((d) => (harvest.value = d)).catch(() => null),
    loadStatus()])
}

async function loadSim() {
  const s = await api(`/api/simulation/${enc(props.sim)}`)
  detail.value = { title: `Simulation ${props.sim}`, simulation_id: props.sim, files: [], manifest: { started_at: s.created_at }, summary: {}, simulation_on_backend: true }
  const base = `/api/simulation/${enc(props.sim)}`
  await Promise.all([
    api(`${base}/config`).then((d) => (config.value = d)).catch(() => null),
    api(`${base}/feed-test`).then((d) => (feed.value = d)).catch(() => null),
    api(`${base}/feed-story`).then((d) => (story.value = d)).catch(() => null),
    api(`${base}/thought-stream`).then((d) => (harvest.value = d)).catch(() => null),
    s.graph_id ? api(`/api/graph/data/${enc(s.graph_id)}`).then((d) => (graph.value = d)).catch(() => null) : null,
    loadStatus()
  ])
}

async function loadStatus() {
  try {
    if (props.name) status.value = await api(`/api/runs/${enc(props.name)}/status`)
    else {
      const run = await api(`/api/simulation/${enc(props.sim)}/run-status`)
      status.value = { live: true, run, stages: [], rounds: [], started_at: run.started_at, finished_at: run.completed_at }
    }
  } catch {
    status.value = null
  }
  schedulePoll()
}
function schedulePoll() {
  clearTimeout(pollTimer)
  if (alive && isRunning.value && status.value?.live) pollTimer = setTimeout(loadStatus, 5000)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (props.name) await loadRun()
    else await loadSim()
    try {
      messages.value = JSON.parse(localStorage.getItem(storeKey.value) || '[]')
    } catch {
      messages.value = []
    }
    personId.value = people.value[0]?.agent_id ?? null
    if (messages.value.length) nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight }))
  } catch (e) {
    error.value = e.message
    detail.value = null
  } finally {
    loading.value = false
  }
  if (detail.value && pending.value) {
    const p = pending.value
    pending.value = null
    agent.value = p.agent
    attachment.value = p.attachment || null
    await nextTick()
    ask(p.text)
  }
}
watch(key, load, { immediate: true })
onBeforeUnmount(() => {
  alive = false
  clearTimeout(pollTimer)
})
watch(messages, (v) => {
  try {
    localStorage.setItem(storeKey.value, JSON.stringify(v.slice(-80)))
    window.dispatchEvent(new Event('mm-chat-saved'))
  } catch {
    /* private mode: chat still works for this page */
  }
}, { deep: true })

const mk = computed(() => detail.value?.summary?.marketing || null)
const index = computed(() => config.value?.persona_index || [])
const people = computed(() => index.value.filter((r) => (r.kind || 'persona') === 'persona'))
const segments = computed(() => [...new Set(people.value.map((r) => r.segment).filter(Boolean))])
const communities = computed(() => index.value.filter((r) => r.kind === 'community'))
const decision = computed(() => detail.value?.summary?.decision?.decision || detail.value?.decision || '')
const decisionClass = computed(() => decision.value.toLowerCase().replace(' ', '-'))
const runData = computed(() => ({ summary: detail.value?.summary, feed: feed.value, index: index.value }))

const steps = computed(() => {
  if (!detail.value) return []
  const m = detail.value.manifest || {}
  const fresh = !messages.value.length // once there is a chat, the steps fold away so the conversation stays in view
  const out = [{
    id: 'people', title: `${people.value.length || detail.value.people || 0} simulated people created`,
    time: fmtTime(m.started_at), chart: peopleOption(index.value), chartTitle: 'People by country', height: 220, open: false
  }]
  if (feed.value) out.push({ id: 'feed', title: 'Ads scrolled in realistic feeds', chart: creativesOption(feed.value), chartTitle: 'Expected click-through per ad', open: fresh })
  if (mk.value) {
    out.push({ id: 'intent', title: 'Buyer survey answered', chart: intentOption(mk.value), chartTitle: 'Purchase intent', open: fresh })
    const seg = segmentsOption(mk.value)
    if (seg) out.push({ id: 'segments', title: 'Which audience to target', chart: seg, chartTitle: 'Would convert by segment', height: 60 + 28 * Math.min(12, mk.value.by_segment.length), text: mk.value.segment_shrink?.note, open: false })
    const obj = objectionsOption(mk.value)
    if (obj) out.push({ id: 'objections', title: 'Why people said no', chart: obj, chartTitle: 'Objections', quotes: (mk.value.objections || []).slice(0, 2).flatMap((o) => (o.examples || []).slice(0, 1).map((ex) => ({ text: ex.text, who: `${ex.name} · ${ex.segment}` }))), open: false })
  }
  const files = ['disclosure.md', 'real_check.csv', 'report.md', 'market_report.md'].filter((f) => detail.value.files.includes(f))
  if (files.length || detail.value.has_dashboard) {
    out.push({ id: 'files', title: 'Report and files', time: fmtTime(m.finished_at), files, open: false,
      text: files.includes('real_check.csv') ? 'real_check.csv holds the questions that decided this run, to ask real people.' : '' })
  }
  return out
})

const webgl = hasWebGL()
const market3d = computed(() => (props.theme, webgl ? marketGraph(index.value, graph.value) : null))
const market3dLabel = computed(() => {
  const c = market3d.value?.counts || {}
  return `3D market: ${c.people || 0} simulated people in ${c.segments || 0} segments, ${c.communities || 0} communities and ${c.entities || 0} market map entities. Drag to turn, scroll to zoom.`
})
const market2d = computed(() => (props.theme, webgl ? null : market2dOption(index.value, graph.value)))

const kindLabel = { private_thought: 'thought', said: 'said', posted: 'posted' }
const thoughts = computed(() => {
  const p = palette()
  const segs = segments.value
  const color = (seg) => p.series[Math.max(0, segs.indexOf(seg)) % p.series.length]
  return (harvest.value?.entries || []).filter((e) => e.text).map((e) => ({
    who: e.name || `Person ${e.agent_id}`, segment: e.segment, source: e.source, kind: e.kind, text: e.text, did: e.did, context: e.context, color: color(e.segment)
  }))
})
const thoughtSources = computed(() => Object.entries(harvest.value?.by_source || {}).filter(([s]) => s))
const shownThoughts = computed(() => (thoughtSource.value ? thoughts.value.filter((t) => t.source === thoughtSource.value) : thoughts.value).slice(0, 150))

const platformLabel = (p) => ({ twitter: 'Twitter-style', reddit: 'Reddit-style' })[p] || p
const platforms = computed(() => Object.keys(story.value?.platforms || {}))
watch(platforms, (v) => {
  if (!v.includes(platform.value)) platform.value = v[0] || ''
}, { immediate: true })
const posts = computed(() => {
  const list = story.value?.platforms?.[platform.value]?.posts || story.value?.brand_posts || []
  return list.slice(0, 80).map((x) => ({
    who: x.author?.name || 'Someone', segment: x.author?.segment, country: x.author?.country, brand: !!x.is_brand,
    round: x.round, text: x.content || x.quote_content || '', likes: x.likes || 0, dislikes: x.dislikes || 0,
    quotes: (x.quotes || []).length, comments: Array.isArray(x.comments) ? x.comments : []
  })).filter((x) => x.text)
})

const isRunning = computed(() => ['running', 'starting', 'paused'].includes(status.value?.run?.runner_status))
const progress = computed(() => {
  const r = status.value?.run || {}
  const pct = r.progress_percent ?? (r.total_rounds ? (100 * (r.current_round || 0)) / r.total_rounds : 0)
  return Math.max(0, Math.min(100, Math.round(pct)))
})
const statusLabel = computed(() => {
  const s = status.value?.run?.runner_status
  if (!s || s === 'idle') return status.value?.finished_at ? 'Finished' : 'Not started'
  if (s === 'stopping' && progress.value >= 100) return 'Finished'
  return s.charAt(0).toUpperCase() + s.slice(1)
})
const roundsChart = computed(() => (props.theme, roundsOption(status.value?.rounds || [])))

const suggestions = computed(() => {
  const base = ['Which audience should we target?', 'Why did people say no?', 'Which ad worked best?', 'How many would buy?', 'Who did we simulate?']
  const q = draft.value.trim().toLowerCase()
  return (q ? base.filter((s) => s.toLowerCase().includes(q)) : base).slice(0, 5)
})
const showSuggest = computed(() => focused.value && agent.value === 'run' && suggestions.value.length > 0 && !busy.value)
const placeholder = computed(() => ({
  run: 'Ask about this run: audience, objections, ads, intent…',
  person: 'Ask this simulated person anything…',
  report: 'Ask the report agent about this run…',
  focus: 'One discussion question per line (Shift+Enter for a new line)…'
})[agent.value])
const needsBackend = computed(() => agentById(agent.value).paid && !onBackend.value)
const canSend = computed(() => !!draft.value.trim() && !busy.value && !needsBackend.value && (agent.value !== 'person' || personId.value !== null))
const modeNote = computed(() => {
  if (needsBackend.value) return `${agentById(agent.value).label} needs this run's simulation (${sid.value || 'none'}) on this backend. The saved results still answer under Results.`
  const model = props.provider?.models?.[0]?.model
  const via = model ? ` (${model})` : ''
  return ({
    run: 'Answers come from the saved results, with a chart. No model call.',
    person: `Sends one model call to your provider${via}. The reply is written by a model playing this invented person.`,
    report: `Sends one or more model calls to your provider${via}. The agent reads the simulated run, not real buyers.`,
    focus: `Sends about 4 model calls per person per question to your provider${via}, then shows the transcript. Simulated.`
  })[agent.value]
})

function chartFor(m) {
  const map = { segments: segmentsOption, objections: objectionsOption, intent: intentOption, decision: intentOption }
  if (m.chartKey === 'creatives') return creativesOption(feed.value)
  if (m.chartKey === 'people') return peopleOption(index.value)
  return map[m.chartKey] ? map[m.chartKey](mk.value) : null
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
    if (showSuggest.value && !draft.value.trim()) ask(suggestions.value[active.value])
    else if (canSend.value) ask(draft.value)
  }
}
function onTabKey(e) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
  e.preventDefault()
  const i = tabs.findIndex((t) => t.id === tab.value)
  const n = tabs.length
  const next = e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : (i + (e.key === 'ArrowRight' ? 1 : n - 1)) % n
  tab.value = tabs[next].id
  nextTick(() => document.getElementById(`ws-tab-${tab.value}`)?.focus())
}
async function onAttach(e) {
  const f = e.target.files?.[0]
  e.target.value = ''
  if (!f) return
  if (f.size > 60000) {
    error.value = 'Attach a text file under 60 KB.'
    return
  }
  attachment.value = { name: f.name, text: (await f.text()).slice(0, 60000) }
}

const say = (m) => messages.value.push({ at: Date.now(), ...m })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function runFocusGroup(text, files) {
  const guide = text.split('\n').map((q) => q.trim()).filter(Boolean).slice(0, 8)
  const body = { simulation_id: sid.value, guide, people: groupSize.value, segment: groupSegment.value || undefined }
  if (files) body.offer = files.slice(0, 600)
  const started = await api('/api/simulation/focus-group', { method: 'POST', body })
  busyNote.value = `Focus group running: ${started.people} simulated people, ${started.questions} question${started.questions === 1 ? '' : 's'}…`
  for (let i = 0; i < 400 && alive; i++) {
    await sleep(3000)
    const t = await api('/api/simulation/market-task/status', { method: 'POST', body: { task_id: started.task_id } })
    if (t.status === 'failed') throw new Error(t.error || 'the focus group failed')
    if (t.status === 'completed') break
    if (t.message) busyNote.value = `Focus group: ${t.message}`
  }
  const res = await api(`/api/simulation/${enc(sid.value)}/focus-group`)
  const shift = res.shift || {}
  const parts = (res.participants || []).map((p) => `${p.id} (${p.segment || 'no segment'}): ${p.pre} → ${p.post}`)
  const themes = (res.themes || []).map((t) => `• ${t.title} (${t.tone})`).join('\n')
  say({
    role: 'assistant', who: `Focus group of ${parts.length} simulated people`, agent: 'focus', simulated: true,
    text: [`Private verdict before → after the discussion:\n${parts.join('\n')}`,
      shift.note || (shift.moved !== undefined ? `${shift.moved} changed their mind.` : ''),
      themes ? `Themes:\n${themes}` : ''].filter(Boolean).join('\n\n'),
    transcript: (res.transcript || []).slice(0, 120)
  })
}

async function ask(text) {
  text = (text || '').trim()
  if (!text || busy.value) return
  const who = agent.value
  if (agentById(who).paid && !onBackend.value) {
    say({ role: 'assistant', text: modeNote.value })
    return
  }
  const att = attachment.value
  const files = att ? `\n\n[Attached ${att.name}]\n${att.text}` : ''
  draft.value = ''
  attachment.value = null
  say({ role: 'user', agent: who, text: text + (att ? `\n📎 ${att.name}` : '') })
  busy.value = true
  busyNote.value = who === 'run' ? 'Reading the saved results…' : 'Waiting for the model…'
  try {
    if (who === 'run') {
      const local = localAnswer(text, runData.value)
      say(local
        ? { role: 'assistant', who: 'From the saved results', simulated: true, text: local.text, chartKey: local.chartKey, caption: local.caption }
        : { role: 'assistant', who: 'From the saved results', text: 'The saved results cover audiences, objections, ads, purchase intent, the people and the decision. For anything else, pick Report agent, Person or Focus group at the top (model calls).' })
    } else if (who === 'person') {
      const history = messages.value.filter((m) => m.agent === 'person' && m.person === personId.value).slice(-6)
        .map((m) => ({ role: m.role === 'user' ? 'user' : 'person', text: m.text }))
      messages.value[messages.value.length - 1].person = personId.value
      const r = await api('/api/simulation/ask', { method: 'POST', body: { simulation_id: sid.value, agent_id: personId.value, message: text + files, history } })
      say({ role: 'assistant', who: `${r.name} · ${r.segment || 'no segment'}`, agent: 'person', person: personId.value, simulated: true, text: r.reply })
    } else if (who === 'report') {
      const chat_history = messages.value.filter((m) => m.agent === 'report').slice(-9, -1).map((m) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }))
      const r = await api('/api/report/chat', { method: 'POST', body: { simulation_id: sid.value, message: text + files, chat_history } })
      const tools = (r.tool_calls || []).length
      say({ role: 'assistant', who: `Report agent${tools ? ` · used ${tools} tool${tools === 1 ? '' : 's'}` : ''}`, agent: 'report', simulated: true, text: r.response || r.answer || JSON.stringify(r) })
    } else {
      await runFocusGroup(text, att?.text || '')
    }
  } catch (e) {
    say({ role: 'assistant', who: agentById(who).label, text: `Could not answer: ${e.message}` })
  } finally {
    busy.value = false
    focused.value = false
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
