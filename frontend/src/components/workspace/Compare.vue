<template>
  <div class="ws-section ws-page">
    <header class="ws-page-head">
      <h1><Ico name="compare" :size="20" />Compare runs</h1>
      <p>Two saved runs side by side. Every number is simulated: read the direction of a difference, not its size.</p>
    </header>

    <div class="ws-compare-pick">
      <label v-for="(side, i) in ['a', 'b']" :key="side" class="ws-compare-select">
        <span>Run {{ i === 0 ? 'A' : 'B' }}</span>
        <select :value="picks[side]" class="ws-chip" :aria-label="`Run ${i === 0 ? 'A' : 'B'}`" @change="choose(side, $event.target.value)">
          <option value="">Pick a run…</option>
          <option v-for="r in runs" :key="r.name" :value="r.name">{{ r.title }} · {{ r.name }}</option>
        </select>
      </label>
      <button type="button" class="ws-icon-btn bordered" aria-label="Swap A and B" title="Swap A and B" :disabled="!picks.a || !picks.b" @click="swap"><Ico name="swap" /></button>
    </div>

    <p v-if="loading" class="ws-empty" role="status">Loading…</p>
    <template v-else-if="A && B">
      <div class="ws-compare-table" role="table" aria-label="Key numbers, simulated">
        <div class="ws-compare-row head" role="row">
          <span role="columnheader">Measure</span>
          <span v-for="(r, i) in [A, B]" :key="i" role="columnheader">
            <RouterLink :to="`/workspace/runs/${r.name}`">{{ r.title }} <Ico name="external" :size="12" /></RouterLink>
          </span>
        </div>
        <div v-for="row in rows" :key="row.label" class="ws-compare-row" role="row">
          <span role="rowheader"><Ico :name="row.icon" :size="14" />{{ row.label }}</span>
          <span v-for="(v, i) in row.values" :key="i" role="cell" :class="{ lead: row.lead === i }">
            {{ v ?? '–' }}<small v-if="row.lead === i" class="ws-tagx accent">higher</small>
          </span>
        </div>
      </div>
      <p v-if="gapNote" class="ws-note"><Ico name="shield" :size="12" /> {{ gapNote }}</p>

      <div class="ws-compare-charts">
        <div v-for="(r, i) in [A, B]" :key="i" class="ws-box">
          <h4>{{ i === 0 ? 'A' : 'B' }} · purchase intent <small>simulated</small></h4>
          <EChart v-if="intentOption(r.mk)" :option="intentOption(r.mk)" :height="230" :label="`Purchase intent for ${r.title}`" :theme="theme" />
          <p v-else class="ws-empty">No buyer survey in this run.</p>
        </div>
      </div>
    </template>
    <div v-else class="ws-read-empty" style="min-height: 240px">
      <Ico name="compare" :size="32" />
      <b>Pick two runs</b>
      <span>Choose run A and run B above. The choice stays in the page address, so you can come back to it.</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import EChart from './EChart.vue'
import Ico from './Ico.vue'
import { api } from '../../workspace/api.js'
import { intentOption } from '../../workspace/charts.js'

const props = defineProps({ runs: { type: Array, default: () => [] }, theme: { type: String, default: 'dark' } })
const route = useRoute(), router = useRouter()
const picks = computed(() => ({ a: String(route.query.a || ''), b: String(route.query.b || '') }))
const A = ref(null), B = ref(null), loading = ref(false)
const cache = new Map()

function choose(side, name) {
  router.replace({ query: { ...route.query, [side]: name || undefined } })
}
function swap() {
  router.replace({ query: { a: picks.value.b, b: picks.value.a } })
}

async function loadOne(name) {
  if (!name) return null
  if (cache.has(name)) return cache.get(name)
  const enc = encodeURIComponent(name)
  const d = await api(`/api/runs/${enc}`)
  const has = new Set(d.files)
  const [feed, config] = await Promise.all([
    has.has('feed_test.json') ? api(`/api/runs/${enc}/files/feed_test.json`).catch(() => null) : null,
    has.has('config.json') ? api(`/api/runs/${enc}/files/config.json`).catch(() => null) : null
  ])
  const people = (config?.persona_index || []).filter((r) => (r.kind || 'persona') === 'persona')
  const run = { name, title: d.title, decision: d.summary?.decision?.decision || d.decision, mk: d.summary?.marketing || null, feed, people,
    count: people.length || Number(d.people) || null }
  cache.set(name, run)
  return run
}

watch(picks, async (p) => {
  loading.value = true
  try {
    ;[A.value, B.value] = await Promise.all([loadOne(p.a), loadOne(p.b)])
  } catch {
    A.value = B.value = null
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
const lead = (a, b) => (num(a) === null || num(b) === null || a === b ? null : a > b ? 0 : 1)
const rows = computed(() => {
  if (!A.value || !B.value) return []
  const [a, b] = [A.value, B.value]
  const ya = a.mk?.overall?.convert_yes, yb = b.mk?.overall?.convert_yes
  const ba = bestAd(a), bb = bestAd(b)
  return [
    { icon: 'check', label: 'Decision', values: [a.decision ? String(a.decision).toUpperCase() : null, b.decision ? String(b.decision).toUpperCase() : null] },
    { icon: 'users', label: 'Simulated people', values: [a.count?.toLocaleString(), b.count?.toLocaleString()] },
    { icon: 'trend', label: 'Would convert', values: [pct(ya), pct(yb)], lead: lead(ya, yb) },
    { icon: 'circle', label: 'Maybe', values: [pct(a.mk?.overall?.convert_maybe), pct(b.mk?.overall?.convert_maybe)] },
    { icon: 'target', label: 'Top segment', values: [topSegment(a), topSegment(b)] },
    { icon: 'no', label: 'Top objection', values: [a.mk?.objections?.[0] ? `${a.mk.objections[0].label} (${a.mk.objections[0].share}%)` : null, b.mk?.objections?.[0] ? `${b.mk.objections[0].label} (${b.mk.objections[0].share}%)` : null] },
    { icon: 'megaphone', label: 'Best ad (expected click-through)', values: [ba ? `${ba.name} · ${ba.ctr}%` : null, bb ? `${bb.name} · ${bb.ctr}%` : null], lead: lead(ba?.ctr, bb?.ctr) }
  ]
})
const gapNote = computed(() => {
  const a = A.value?.mk?.overall, b = B.value?.mk?.overall
  if (!a || !b || num(a.convert_yes) === null || num(b.convert_yes) === null) return ''
  const gap = Math.abs(a.convert_yes - b.convert_yes)
  const small = Math.min(a.n || 0, b.n || 0)
  if (gap < 5 || small < 30) return `The intent gap is ${gap.toFixed(1)} points with ${small || 'few'} people in the smaller run: too close to call. Check with real people.`
  return `The intent gap is ${gap.toFixed(1)} points. Simulated gaps tend to run larger than real ones, so treat it as which way to lean, not by how much.`
})
</script>
