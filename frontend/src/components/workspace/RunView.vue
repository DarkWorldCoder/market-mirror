<template>
  <div class="ws-run">
    <div class="ws-run-main" ref="scroller">
      <p v-if="loading" class="ws-empty">Loading the run…</p>
      <template v-else-if="detail">
        <div class="ws-title">
          <h2>{{ detail.title }}</h2>
          <span v-if="decision" class="pill" :class="decisionClass">{{ decision.toUpperCase() }}</span>
          <span class="pill">Simulated</span>
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
                <button v-for="f in step.files" :key="f" class="ws-file" @click="fetchFile(f)">
                  <i>{{ f.split('.').pop().toUpperCase() }}</i>{{ f }} <span aria-hidden="true">↓</span>
                </button>
                <button v-if="detail.has_dashboard" class="ws-file" @click="openDashboard">
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

        <div class="ws-chat" aria-live="polite">
          <div v-for="(m, i) in messages" :key="i" class="ws-msg" :class="{ me: m.role === 'user' }">
            <small>{{ m.role === 'user' ? 'You' : m.who || 'MarketMirror' }}</small>{{ m.text }}
            <div v-if="m.chartKey && chartFor(m)" class="ws-box" style="margin-top: 10px">
              <EChart :option="chartFor(m)" :height="240" :label="m.caption" :caption="m.caption" :theme="theme" />
            </div>
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
              <button class="ws-send" :disabled="!draft.trim() || busy" aria-label="Send" @click="ask(draft)">↑</button>
            </div>
            <p class="ws-note">{{ modeNote }}</p>
          </div>
          <p class="ws-disclaimer">Simulated people, not real buyers. Check decisions with real people before you spend.</p>
        </div>
      </template>
      <p v-else class="ws-empty">{{ error || 'Run not found.' }}</p>
    </div>

    <aside class="ws-run-side" aria-label="Run visuals">
      <div class="ws-tabs" role="tablist">
        <button v-for="t in tabs" :key="t.id" role="tab" :aria-selected="tab === t.id" @click="tab = t.id">
          {{ t.label }}
        </button>
      </div>
      <div class="ws-tabpanel" role="tabpanel">
        <template v-if="tab === 'thinking'">
          <p class="ws-note" style="margin-bottom: 6px">
            What the simulated people said and thought, from the saved answers. Written by a model playing each person.
          </p>
          <div v-for="(t, i) in thoughts" :key="i" class="ws-thought">
            <header>
              <span class="ws-dot" :style="{ background: t.color }"></span>{{ t.who }} · {{ t.where }}
            </header>
            {{ t.text }}
          </div>
          <p v-if="!thoughts.length" class="ws-empty">No saved thoughts in this run.</p>
        </template>
        <template v-else-if="tab === 'market'">
          <EChart v-if="webgl && market3d" :option="market3d" :height="430" gl label="3D market of simulated people" :theme="theme" />
          <EChart v-else-if="market2d" :option="market2d" :height="430" label="Market map of simulated people" :theme="theme" />
          <p class="ws-note">
            {{ webgl ? 'Each point is one invented person, grouped by segment; diamonds are entities from the market map. Drag to turn, scroll to zoom.' : 'This browser has no 3D (WebGL), so the market shows as a map: each dot is one invented person, linked to their segment. Drag and scroll to explore.' }}
            Positions show grouping, not measured distance.
          </p>
        </template>
        <template v-else>
          <div v-for="(post, i) in posts" :key="i" class="ws-thought">
            <header>{{ post.who }} · {{ post.platform }}<template v-if="post.score"> · {{ post.score }} votes</template></header>
            {{ post.text }}
          </div>
          <p v-if="!posts.length" class="ws-empty">No social posts saved in this run.</p>
        </template>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import EChart from './EChart.vue'
import { api, download, openHtml } from '../../workspace/api.js'
import {
  creativesOption, hasWebGL, intentOption, localAnswer, market2dOption, marketOption, objectionsOption, palette, peopleOption, segmentsOption
} from '../../workspace/charts.js'

const props = defineProps({ name: { type: String, required: true }, theme: { type: String, default: 'light' } })

const detail = ref(null), loading = ref(true), error = ref('')
const survey = ref(null), feed = ref(null), graph = ref(null), config = ref(null), story = ref(null), stream = ref(null)
const tab = ref('thinking')
const tabs = [{ id: 'thinking', label: 'Thinking' }, { id: 'market', label: '3D market' }, { id: 'feed', label: 'Social feed' }]
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

async function load() {
  loading.value = true
  error.value = ''
  try {
    detail.value = await api(`/api/runs/${encodeURIComponent(props.name)}`)
    const has = new Set(detail.value.files)
    const get = (f, target) => (has.has(f) ? api(`/api/runs/${encodeURIComponent(props.name)}/files/${f}`).then((d) => (target.value = d)).catch(() => null) : null)
    await Promise.all([get('survey.json', survey), get('feed_test.json', feed), get('graph.json', graph),
      get('config.json', config), get('feed_story.json', story), get('thought_stream.json', stream)])
    try {
      messages.value = JSON.parse(localStorage.getItem(storeKey.value) || '[]')
    } catch {
      messages.value = []
    }
    personId.value = people.value[0]?.agent_id ?? null
  } catch (e) {
    error.value = e.message
    detail.value = null
  } finally {
    loading.value = false
  }
}
watch(() => props.name, load, { immediate: true })
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

const steps = computed(() => {
  if (!detail.value) return []
  const m = detail.value.manifest || {}
  const t = props.theme // eslint-disable-line no-unused-vars -- options read theme colours
  const out = [{
    id: 'people', title: `${people.value.length || detail.value.people || 0} simulated people created`,
    time: fmtTime(m.started_at), chart: peopleOption(index.value), chartTitle: 'People by country', height: 220, open: false
  }]
  if (feed.value) out.push({ id: 'feed', title: 'Ads scrolled in realistic feeds', chart: creativesOption(feed.value), chartTitle: 'Expected click-through per ad', open: true })
  if (mk.value) {
    out.push({ id: 'intent', title: 'Buyer survey answered', chart: intentOption(mk.value), chartTitle: 'Purchase intent', open: true })
    const seg = segmentsOption(mk.value)
    if (seg) out.push({ id: 'segments', title: 'Which audience to target', chart: seg, chartTitle: 'Would convert by segment', height: 60 + 28 * Math.min(12, mk.value.by_segment.length), text: mk.value.segment_shrink?.note, open: true })
    const obj = objectionsOption(mk.value)
    if (obj) out.push({ id: 'objections', title: 'Why people said no', chart: obj, chartTitle: 'Objections', quotes: (mk.value.objections || []).slice(0, 2).flatMap((o) => (o.examples || []).slice(0, 1).map((ex) => ({ text: ex.text, who: `${ex.name} · ${ex.segment}` }))), open: false })
  }
  const files = ['disclosure.md', 'real_check.csv', 'report.md', 'market_report.md'].filter((f) => detail.value.files.includes(f))
  out.push({ id: 'files', title: 'Report and files', time: fmtTime(m.finished_at), files, open: true,
    text: files.includes('real_check.csv') ? 'real_check.csv holds the questions that decided this run, to ask real people.' : '' })
  return out
})

const webgl = hasWebGL()
const market3d = computed(() => (props.theme, webgl ? marketOption(index.value, graph.value) : null))
const market2d = computed(() => (props.theme, webgl ? null : market2dOption(index.value, graph.value)))

const thoughts = computed(() => {
  const p = palette()
  const segs = [...new Set(people.value.map((r) => r.segment))]
  const color = (seg) => p.series[Math.max(0, segs.indexOf(seg)) % p.series.length]
  const byId = Object.fromEntries(index.value.map((r) => [r.agent_id, r]))
  const out = []
  for (const t of (stream.value?.thoughts || stream.value?.items || []).slice(0, 80)) {
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
  for (const s of (feed.value?.sessions || []).slice(0, 400)) {
    if (s.ad?.thought) out.push({ who: s.name, where: `scrolling ${s.platform} · ${s.creative_id}`, text: s.ad.thought, color: color(s.segment) })
  }
  return out.slice(0, 150)
})

const posts = computed(() => {
  const list = story.value?.posts || story.value?.items || []
  return list.slice(0, 60).map((x) => ({ who: x.author || x.name || x.agent_name || 'Someone', platform: x.platform || '', text: x.content || x.text || '', score: x.score || x.net_score || '' })).filter((x) => x.text)
})

const suggestions = computed(() => {
  const base = ['Which audience should we target?', 'Why did people say no?', 'Which ad worked best?', 'How many would buy?', 'Who did we simulate?']
  const q = draft.value.trim().toLowerCase()
  return (q ? base.filter((s) => s.toLowerCase().includes(q)) : base).slice(0, 5)
})
const showSuggest = computed(() => focused.value && mode.value === 'run' && suggestions.value.length > 0 && !busy.value)
const placeholder = computed(() => ({ run: 'Ask about this run: audience, objections, ads, intent…', person: 'Ask this simulated person anything…', report: 'Ask the report agent about this run…' })[mode.value])
const modeNote = computed(() => ({
  run: 'Answers come from the saved results, with a chart. No model call.',
  person: 'Sends one model call to your configured provider. The reply is written by a model playing this invented person.',
  report: 'Sends one or more model calls to your configured provider. Needs the simulation on this backend.'
})[mode.value])

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
      const local = localAnswer(text, runData.value)
      messages.value.push(local
        ? { role: 'assistant', text: local.text, chartKey: local.chartKey, caption: local.caption }
        : { role: 'assistant', text: 'The saved results cover audiences, objections, ads, purchase intent, the people and the decision. For anything else, switch to "Ask a person" or "Report agent" (model calls).' })
    } else if (mode.value === 'person') {
      const sid = detail.value.simulation_id
      const history = messages.value.filter((m) => m.who && m.agent === personId.value).slice(-6).map((m) => ({ role: m.role === 'user' ? 'user' : 'person', text: m.text }))
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
