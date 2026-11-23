<template>
  <div class="compare">
    <header class="compare-head">
      <h1><GitCompare :size="20" aria-hidden="true" />Compare experiments</h1>
      <p>Two saved runs side by side. Every number is simulated: read which way a difference points, not its size.</p>
    </header>

    <div class="compare-pick">
      <label v-for="side in ['a', 'b']" :key="side">
        <span>Experiment {{ side.toUpperCase() }}</span>
        <select :value="picks[side]" :aria-label="`Experiment ${side.toUpperCase()}`" @change="choose(side, $event.target.value)">
          <option value="">Choose a run…</option>
          <option v-for="r in runs" :key="r.name" :value="r.name">{{ r.title || r.name }} · {{ r.name }}</option>
        </select>
      </label>
      <button type="button" class="compare-swap" aria-label="Swap A and B" title="Swap A and B" :disabled="!picks.a || !picks.b" @click="swap"><ArrowLeftRight :size="16" /></button>
    </div>

    <p v-if="loading" class="compare-empty" role="status">Loading…</p>
    <p v-else-if="loadError" class="compare-empty" role="alert">{{ loadError }}</p>
    <template v-else-if="A && B">
      <div class="compare-table" role="table" aria-label="Key numbers, simulated">
        <div class="compare-row head" role="row">
          <span role="columnheader">Measure</span>
          <span v-for="(r, i) in [A, B]" :key="i" role="columnheader">
            <RouterLink :to="{ path: '/', query: { run: r.name, show: 'reports' } }">{{ r.title }} <ArrowUpRight :size="12" aria-hidden="true" /></RouterLink>
          </span>
        </div>
        <div v-for="row in rows" :key="row.label" class="compare-row" role="row">
          <span role="rowheader"><component :is="row.icon" :size="14" aria-hidden="true" />{{ row.label }}</span>
          <span v-for="(v, i) in row.values" :key="i" role="cell" :class="{ lead: row.lead === i }">
            {{ v ?? '—' }}<small v-if="row.lead === i" class="compare-higher">higher</small>
          </span>
        </div>
      </div>
      <p v-if="gapNote" class="compare-note"><ShieldCheck :size="13" aria-hidden="true" />{{ gapNote }}</p>
      <div class="compare-charts">
        <figure v-for="(r, i) in [A, B]" :key="i" class="compare-chart">
          <figcaption>{{ i === 0 ? 'A' : 'B' }} · purchase intent <small>simulated</small></figcaption>
          <EChart v-if="intentOption(r.mk)" :option="intentOption(r.mk)" :height="230" :label="`Purchase intent for ${r.title}`" :theme="theme" />
          <p v-else class="compare-empty">No buyer survey in this run.</p>
        </figure>
      </div>
    </template>
    <div v-else class="compare-empty big">
      <GitCompare :size="30" aria-hidden="true" />
      <b>Choose two experiments</b>
      <span>The choice stays in the page address, so you can share or return to it.</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ArrowLeftRight, ArrowUpRight, CircleCheck, CircleDashed, GitCompare, Megaphone, ShieldCheck, Target, ThumbsDown, TrendingUp, UsersRound } from 'lucide-vue-next'
import EChart from './EChart.vue'
import { api } from '../../workspace/api'
import { intentOption } from '../../workspace/charts'

defineProps({ runs: { type: Array, default: () => [] }, theme: { type: String, default: 'light' } })
const route = useRoute(), router = useRouter()
const picks = computed(() => ({ a: String(route.query.a || ''), b: String(route.query.b || '') }))
const A = ref(null), B = ref(null), loading = ref(false), loadError = ref('')
const cache = new Map()

const choose = (side, name) => router.replace({ query: { ...route.query, [side]: name || undefined } })
const swap = () => router.replace({ query: { a: picks.value.b, b: picks.value.a } })

async function loadOne(name) {
  if (!name) return null
  if (cache.has(name)) return cache.get(name)
  const enc = encodeURIComponent(name)
  const d = await api(`/api/runs/${enc}`)
  const has = new Set(d.files || [])
  const [feed, config] = await Promise.all([
    has.has('feed_test.json') ? api(`/api/runs/${enc}/files/feed_test.json`).catch(() => null) : null,
    has.has('config.json') ? api(`/api/runs/${enc}/files/config.json`).catch(() => null) : null
  ])
  const people = (config?.persona_index || []).filter((r) => (r.kind || 'persona') === 'persona')
  const run = { name, title: d.title || name, decision: d.summary?.decision?.decision || d.decision, mk: d.summary?.marketing || null, feed, count: people.length || Number(d.people) || null }
  cache.set(name, run)
  return run
}
watch(picks, async (p) => {
  loading.value = true
  loadError.value = ''
  try {
    ;[A.value, B.value] = await Promise.all([loadOne(p.a), loadOne(p.b)])
  } catch (e) {
    A.value = B.value = null
    loadError.value = `Could not open one of the runs: ${e.message}`
  } finally {
    loading.value = false
  }
}, { immediate: true })

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const pct = (v) => (num(v) === null ? null : `${v}%`)
function bestAd(r) {
  const per = r.feed?.summary?.per_creative || {}
  const names = Object.fromEntries((r.feed?.creatives || []).map((c) => [c.id, c.name || c.id]))
  const id = Object.keys(per).filter((k) => num(per[k]?.expected_ctr) !== null).sort((a, b) => per[b].expected_ctr - per[a].expected_ctr)[0]
  return id ? { name: names[id] || id, ctr: per[id].expected_ctr } : null
}
function topSegment(r) {
  const rate = (s) => num(s.expected_convert_yes) ?? num(s.convert_yes) ?? 0
  const top = [...(r.mk?.by_segment || [])].sort((a, b) => rate(b) - rate(a))[0]
  return top ? `${top.key} (${rate(top)}%, n=${top.n})` : null
}
const objection = (r) => (r.mk?.objections?.[0] ? `${r.mk.objections[0].label} (${r.mk.objections[0].share}%)` : null)
const lead = (a, b) => (num(a) === null || num(b) === null || a === b ? null : a > b ? 0 : 1)
const rows = computed(() => {
  if (!A.value || !B.value) return []
  const [a, b] = [A.value, B.value]
  const ya = a.mk?.overall?.convert_yes, yb = b.mk?.overall?.convert_yes
  const ba = bestAd(a), bb = bestAd(b)
  return [
    { icon: CircleCheck, label: 'Decision', values: [a.decision ? String(a.decision).toUpperCase() : null, b.decision ? String(b.decision).toUpperCase() : null] },
    { icon: UsersRound, label: 'Simulated people', values: [a.count?.toLocaleString(), b.count?.toLocaleString()] },
    { icon: TrendingUp, label: 'Would buy', values: [pct(ya), pct(yb)], lead: lead(ya, yb) },
    { icon: CircleDashed, label: 'Maybe', values: [pct(a.mk?.overall?.convert_maybe), pct(b.mk?.overall?.convert_maybe)] },
    { icon: Target, label: 'Strongest audience', values: [topSegment(a), topSegment(b)] },
    { icon: ThumbsDown, label: 'Top objection', values: [objection(a), objection(b)] },
    { icon: Megaphone, label: 'Best ad (expected click-through)', values: [ba ? `${ba.name} · ${ba.ctr}%` : null, bb ? `${bb.name} · ${bb.ctr}%` : null], lead: lead(ba?.ctr, bb?.ctr) }
  ]
})
const gapNote = computed(() => {
  const a = A.value?.mk?.overall, b = B.value?.mk?.overall
  if (!a || !b || num(a.convert_yes) === null || num(b.convert_yes) === null) return ''
  const gap = Math.abs(a.convert_yes - b.convert_yes), small = Math.min(a.n || 0, b.n || 0)
  if (gap < 5 || small < 30) return `The would-buy gap is ${gap.toFixed(1)} points with ${small || 'few'} people in the smaller run: too close to call. Check with real people before choosing.`
  return `The would-buy gap is ${gap.toFixed(1)} points. Simulated gaps tend to be larger than real ones, so treat it as which way to lean, not by how much.`
})
</script>

<style scoped>
.compare { max-width: 1040px; margin: 0 auto; padding: 28px 24px 40px; }
.compare-head h1 { display: flex; align-items: center; gap: 10px; font-size: 22px; font-weight: 650; letter-spacing: -0.3px; }
.compare-head h1 svg { color: var(--accent); }
.compare-head p { color: var(--muted); font-size: 13px; margin-top: 6px; }
.compare-pick { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; margin: 20px 0; }
.compare-pick label { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 220px; font-size: 11.5px; font-weight: 600; color: var(--muted); }
.compare-pick select { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 13px; }
.compare-swap { display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); cursor: pointer; }
.compare-swap:disabled { opacity: 0.4; cursor: not-allowed; }
.compare-table { border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: var(--panel); }
.compare-row { display: grid; grid-template-columns: minmax(150px, 0.8fr) 1fr 1fr; border-top: 1px solid var(--line); font-size: 13px; }
.compare-row:first-child { border-top: 0; }
.compare-row > span { padding: 11px 14px; display: flex; align-items: center; gap: 7px; flex-wrap: wrap; min-width: 0; overflow-wrap: anywhere; }
.compare-row > span + span { border-left: 1px solid var(--line); }
.compare-row.head { background: var(--panel-2); font-weight: 600; }
.compare-row.head a { color: inherit; text-decoration: none; }
.compare-row.head a:hover { color: var(--accent); }
.compare-row [role='rowheader'] { color: var(--muted); }
.compare-row .lead { font-weight: 650; }
.compare-higher { font-size: 11px; font-weight: 500; color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--line)); border-radius: 999px; padding: 0 7px; }
.compare-note { display: flex; gap: 6px; align-items: flex-start; color: var(--muted); font-size: 12.5px; margin-top: 10px; }
.compare-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
.compare-chart { margin: 0; border: 1px solid var(--line); border-radius: 14px; padding: 14px; background: var(--panel); }
.compare-chart figcaption { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; justify-content: space-between; }
.compare-chart small { color: var(--muted); font-weight: 400; }
.compare-empty { color: var(--muted); font-size: 13px; padding: 16px 4px; }
.compare-empty.big { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 56px 20px; text-align: center; }
.compare-empty.big b { color: var(--text); font-size: 14px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 760px) {
  .compare { padding: 20px 16px 32px; }
  .compare-row { grid-template-columns: 1fr 1fr; }
  .compare-row [role='rowheader'] { grid-column: 1 / -1; background: var(--panel-2); padding: 6px 12px; }
  .compare-row [role='rowheader'] + span { border-left: 0; }
  .compare-row.head > span:first-child { display: none; }
  .compare-charts { grid-template-columns: 1fr; }
}
</style>
