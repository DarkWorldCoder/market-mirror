<template>
  <div class="compare" :class="{ embedded }">
    <header v-if="!embedded" class="compare-head">
      <h1><GitCompare :size="20" aria-hidden="true" />Compare experiments</h1>
      <p>Two saved runs side by side. Every number is simulated: read which way a difference points, not its size.</p>
    </header>

    <div class="compare-pick">
      <label v-for="side in ['a', 'b']" :key="side">
        <span>Experiment {{ side.toUpperCase() }}</span>
        <select :value="picks[side]" :aria-label="`Experiment ${side.toUpperCase()}`" @change="choose(side, $event.target.value)">
          <option value="">Choose a run…</option>
          <option v-for="r in runs" :key="r.name" :value="r.name" :title="r.title || r.name">{{ r.title || r.name }}</option>
        </select>
      </label>
      <button type="button" class="compare-swap" aria-label="Swap A and B" title="Swap A and B" :disabled="!picks.a || !picks.b" @click="swap"><ArrowLeftRight :size="16" /></button>
    </div>

    <p v-if="loading" class="compare-empty" role="status">Loading…</p>
    <p v-else-if="loadError" class="compare-empty" role="alert">{{ loadError }}</p>
    <template v-else-if="A && B">
      <p v-if="verdict" class="compare-verdict"><Scale :size="15" aria-hidden="true" />{{ verdict }} <small>Simulated</small></p>
      <div class="compare-table" role="table" aria-label="Every measure, simulated">
        <div class="compare-row head" role="row">
          <span role="columnheader">Measure <small>all simulated</small></span>
          <span v-for="(r, i) in [A, B]" :key="i" role="columnheader">
            <RouterLink :to="{ path: '/', query: { run: r.name, show: 'reports' } }" :title="r.title">{{ i === 0 ? 'A' : 'B' }} · {{ shortText(displayTitle(r.title), 44) }} <ArrowUpRight :size="12" aria-hidden="true" /></RouterLink>
          </span>
        </div>
        <template v-for="section in sections" :key="section.title">
          <div class="compare-row section" role="row"><span role="rowheader" aria-level="3">{{ section.title }}</span></div>
          <div v-for="row in section.rows" :key="`${section.title}-${row.label}`" class="compare-row" role="row">
            <span role="rowheader">{{ row.label }}</span>
            <span v-for="(v, i) in row.values" :key="i" role="cell" :class="{ lead: row.lead === i }">
              <span v-if="v && v.pill" class="compare-pill" :class="v.tone">{{ v.pill }}</span>
              <ol v-else-if="v && v.list" class="compare-list"><li v-for="item in v.list" :key="item">{{ item }}</li></ol>
              <template v-else>{{ v ?? '—' }}</template>
              <small v-if="row.lead === i" class="compare-higher">higher</small>
            </span>
          </div>
        </template>
      </div>
      <p v-if="gapNote" class="compare-note"><ShieldCheck :size="13" aria-hidden="true" />{{ gapNote }}</p>
      <div class="compare-charts">
        <figure v-for="(r, i) in [A, B]" :key="i" class="compare-chart">
          <figcaption :title="r.title"><span>{{ i === 0 ? 'A' : 'B' }} · {{ shortText(displayTitle(r.title), 36) }}: purchase intent</span><small>simulated</small></figcaption>
          <EChart v-if="intentOption(r.mk)" :option="intentOption(r.mk)" :height="230" :label="`Purchase intent for ${r.title}, simulated`" :theme="theme" />
          <p v-else class="compare-empty">No buyer survey in this run.</p>
        </figure>
      </div>
    </template>
    <div v-else class="compare-empty big">
      <GitCompare :size="30" aria-hidden="true" />
      <b>Choose two experiments</b>
      <span v-if="embedded">Your choice is saved with this chat.</span>
      <span v-else>The choice stays in the page address, so you can share or return to it.</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ArrowLeftRight, ArrowUpRight, GitCompare, Scale, ShieldCheck } from 'lucide-vue-next'
import EChart from './EChart.vue'
import { api } from '../../workspace/api'
import { intentOption } from '../../workspace/charts'
import { compareGapNote, compareSections, compareVerdict, displayTitle, shortText } from '../../workspace/compareRuns'

const props = defineProps({
  runs: { type: Array, default: () => [] },
  theme: { type: String, default: 'light' },
  // inside a chat message: no page header, and the picks live on the message instead of the address
  embedded: { type: Boolean, default: false },
  a: { type: String, default: '' },
  b: { type: String, default: '' }
})
const emit = defineEmits(['pick'])
const route = useRoute(), router = useRouter()
const picks = computed(() => (props.embedded
  ? { a: props.a || '', b: props.b || '' }
  : { a: String(route.query.a || ''), b: String(route.query.b || '') }))
const A = ref(null), B = ref(null), loading = ref(false), loadError = ref('')
const cache = new Map()

function setPicks(next) {
  if (props.embedded) emit('pick', { a: next.a || '', b: next.b || '' })
  else router.replace({ query: { ...route.query, a: next.a || undefined, b: next.b || undefined } })
}
const choose = (side, name) => setPicks({ ...picks.value, [side]: name })
const swap = () => setPicks({ a: picks.value.b, b: picks.value.a })

async function loadOne(name) {
  if (!name) return null
  if (cache.has(name)) return cache.get(name)
  const enc = encodeURIComponent(name)
  const d = await api(`/api/runs/${enc}`)
  const has = new Set(d.files || [])
  const file = (f) => (has.has(f) ? api(`/api/runs/${enc}/files/${f}`).catch(() => null) : null)
  const [feed, config, pitch, story] = await Promise.all([file('feed_test.json'), file('config.json'), file('pitch.json'), file('feed_story.json')])
  const people = (config?.persona_index || []).filter((r) => (r.kind || 'persona') === 'persona')
  // in run detail, `summary` is the saved summary.json; the decision's one-line summary sits inside it
  const decision = d.summary?.decision || {}
  const run = {
    name, title: d.title || name,
    decision: decision.decision || d.decision, decisionSummary: decision.summary || null,
    mk: d.summary?.marketing || null, feed, pitch, story,
    count: people.length || (Number(d.people) || null)
  }
  cache.set(name, run)
  return run
}
let loadTicket = 0
watch(() => [picks.value.a, picks.value.b], async ([a, b]) => {
  const mine = ++loadTicket
  loading.value = true
  loadError.value = ''
  try {
    const [ra, rb] = await Promise.all([loadOne(a), loadOne(b)])
    if (mine !== loadTicket) return
    A.value = ra
    B.value = rb
  } catch (e) {
    if (mine !== loadTicket) return
    A.value = B.value = null
    loadError.value = `Could not open one of the runs: ${e.message}`
  } finally {
    if (mine === loadTicket) loading.value = false
  }
}, { immediate: true })

const sections = computed(() => compareSections(A.value, B.value))
const verdict = computed(() => compareVerdict(A.value, B.value))
const gapNote = computed(() => compareGapNote(A.value, B.value))
</script>

<style scoped>
.compare { max-width: 1040px; margin: 0 auto; padding: 28px 24px 40px; }
.compare.embedded { max-width: none; margin: 14px 0 0; padding: 0; }
.compare-head h1 { display: flex; align-items: center; gap: 10px; font-size: 22px; font-weight: 650; letter-spacing: -0.3px; }
.compare-head h1 svg { color: var(--accent); }
.compare-head p { color: var(--muted); font-size: 13px; margin-top: 6px; }
.compare-pick { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; margin: 20px 0; }
.compare.embedded .compare-pick { margin: 0 0 14px; }
.compare-pick label { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 200px; font-size: 11.5px; font-weight: 600; color: var(--muted); }
.compare-pick select { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 13px; text-overflow: ellipsis; }
.compare-swap { display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); cursor: pointer; }
.compare-swap:disabled { opacity: 0.4; cursor: not-allowed; }
.compare-verdict { display: flex; align-items: flex-start; gap: 8px; margin: 0 0 12px; font-size: 14px; line-height: 1.55; color: var(--text); }
.compare-verdict svg { flex: none; margin-top: 3px; color: var(--accent); }
.compare-verdict small, .compare-row.head small { font-size: 10.5px; font-weight: 500; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; white-space: nowrap; }
.compare-table { border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: var(--panel); }
.compare-row { display: grid; grid-template-columns: minmax(140px, 0.75fr) 1fr 1fr; border-top: 1px solid var(--line); font-size: 13px; line-height: 1.5; }
.compare-row:first-child { border-top: 0; }
.compare-row > span { padding: 10px 14px; display: flex; align-items: center; gap: 7px; flex-wrap: wrap; min-width: 0; overflow-wrap: anywhere; }
.compare-row > span + span { border-left: 1px solid var(--line); }
.compare-row.head { background: var(--panel-2); font-weight: 600; }
.compare-row.head a { color: inherit; text-decoration: none; }
.compare-row.head a:hover { color: var(--accent); }
.compare-row.section { display: block; background: var(--panel-2); }
.compare-row.section > span { padding: 7px 14px; font-size: 12px; font-weight: 650; color: var(--text); }
.compare-row [role='rowheader'] { color: var(--muted); }
.compare-row.section [role='rowheader'] { color: var(--text); }
.compare-row .lead { font-weight: 650; }
.compare-higher { font-size: 11px; font-weight: 500; color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--line)); border-radius: 999px; padding: 0 7px; }
.compare-pill { font-size: 12px; font-weight: 600; border-radius: 999px; padding: 1px 10px; border: 1px solid var(--line); }
.compare-pill.go { color: var(--yes); border-color: color-mix(in srgb, var(--yes) 45%, var(--line)); }
.compare-pill.iterate { color: var(--maybe); border-color: color-mix(in srgb, var(--maybe) 50%, var(--line)); }
.compare-pill.stop { color: var(--no); border-color: color-mix(in srgb, var(--no) 45%, var(--line)); }
.compare-list { margin: 0; padding-left: 18px; display: grid; gap: 3px; }
.compare-note { display: flex; gap: 6px; align-items: flex-start; color: var(--muted); font-size: 12.5px; margin-top: 10px; }
.compare-note svg { flex: none; margin-top: 3px; }
.compare-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
.compare-chart { margin: 0; border: 1px solid var(--line); border-radius: 14px; padding: 14px; background: var(--panel); min-width: 0; }
.compare-chart figcaption { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; justify-content: space-between; gap: 8px; }
.compare-chart figcaption span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.compare-chart small { color: var(--muted); font-weight: 400; flex: none; }
.compare-empty { color: var(--muted); font-size: 13px; padding: 16px 4px; }
.compare-empty.big { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 56px 20px; text-align: center; }
.compare.embedded .compare-empty.big { padding: 28px 16px; border: 1px dashed var(--line); border-radius: 14px; }
.compare-empty.big b { color: var(--text); font-size: 14px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 760px) {
  .compare { padding: 20px 16px 32px; }
  .compare.embedded { padding: 0; }
  .compare-row { grid-template-columns: 1fr 1fr; }
  .compare-row [role='rowheader'] { grid-column: 1 / -1; background: var(--panel-2); padding: 6px 12px; }
  .compare-row.section [role='rowheader'] { background: transparent; }
  .compare-row.section { background: color-mix(in srgb, var(--accent) 8%, var(--panel-2)); }
  .compare-row [role='rowheader'] + span { border-left: 0; }
  .compare-row.head > span:first-child { display: none; }
  .compare-charts { grid-template-columns: 1fr; }
}
</style>
