<template>
  <section class="br" aria-label="What the simulated buyers said">
    <div v-if="summary.asked" class="br-summary">
      <div class="br-bar" role="img" :aria-label="`Survey answers: ${summary.verdicts.yes} would buy, ${summary.verdicts.maybe} maybe, ${summary.verdicts.no} would not, of ${summary.asked} (simulated)`">
        <i v-for="v in verdictKeys" :key="v" :class="v" :style="{ width: pct(summary.verdicts[v]) + '%' }"></i>
      </div>
      <ul class="br-legend">
        <li v-for="v in verdictKeys" :key="v"><span :class="['br-dot', v]" aria-hidden="true"></span>{{ verdictLabel[v] }} <b>{{ summary.verdicts[v] }}</b> <small>{{ pct(summary.verdicts[v]) }}%</small></li>
        <li class="br-sim">of {{ summary.asked.toLocaleString() }} survey answers · simulated</li>
      </ul>
    </div>

    <div class="br-tools">
      <label class="br-search"><Search :size="14" aria-hidden="true" /><span class="sr-only">Search what people said</span>
        <input v-model="q" type="search" placeholder="Search words, names or places" />
      </label>
      <div class="br-chips" role="group" aria-label="Filter by answer">
        <button v-for="c in verdictChips" :key="c.id" type="button" :aria-pressed="verdict === c.id" @click="verdict = verdict === c.id ? '' : c.id">
          <span v-if="c.id && c.id !== 'none'" :class="['br-dot', c.id]" aria-hidden="true"></span>{{ c.label }}
        </button>
      </div>
      <div class="br-chips" role="group" aria-label="Filter by where it was said">
        <button v-for="c in sourceChips.filter((x) => summary.sources[x.id])" :key="c.id" type="button" :aria-pressed="source === c.id" @click="source = source === c.id ? '' : c.id">{{ c.label }} <small>{{ summary.sources[c.id] || 0 }}</small></button>
      </div>
      <select v-if="segments.length > 1" v-model="segment" aria-label="Filter by segment">
        <option value="">All segments</option>
        <option v-for="s in segments" :key="s.key" :value="s.key">{{ s.key }} ({{ s.n }})</option>
      </select>
    </div>

    <div v-if="summary.objections.length" class="br-reasons" role="group" aria-label="Filter by what held them back">
      <span>What held them back</span>
      <button v-for="o in summary.objections.slice(0, 8)" :key="o.key" type="button" :aria-pressed="objection === o.key" @click="objection = objection === o.key ? '' : o.key">
        {{ plainLabel(o.key) }} <small>{{ o.n }}</small>
      </button>
    </div>

    <div class="br-head">
      <p>{{ shown.length.toLocaleString() }} of {{ rows.length.toLocaleString() }} things people said or thought <small>· written by a model playing each person</small></p>
      <button v-if="filtered" type="button" class="br-clear" @click="clear"><X :size="13" aria-hidden="true" />Clear filters</button>
    </div>

    <WorkspacePager v-model:page="page" :size="size" :total="shown.length" label="responses" />
    <ol class="br-list">
      <li v-for="r in paged" :key="r.id" class="br-item">
        <span class="br-avatar" :style="{ background: colorOf(r.segment) }" aria-hidden="true">{{ initials(r.name) }}</span>
        <div class="br-body">
          <header>
            <b>{{ r.name }}</b>
            <small>{{ [r.segment, r.city || r.country].filter(Boolean).join(' · ') }}</small>
            <span v-if="r.verdict" :class="['br-pill', r.verdict]">{{ verdictLabel[r.verdict] }}</span>
            <span class="br-src">{{ sourceLabel[r.source] }}<template v-if="r.detail"> · {{ r.detail }}</template></span>
          </header>
          <p class="br-text">{{ r.text }}</p>
          <p v-if="r.objection" class="br-meta"><b>Held back by:</b> {{ r.objection }}</p>
          <p v-if="r.change" class="br-meta"><b>Would change their mind:</b> {{ r.change }}</p>
          <button v-if="r.agentId" type="button" class="br-ask" @click="$emit('ask', r.agentId)"><MessageCircle :size="13" aria-hidden="true" />Ask {{ firstName(r.name) }}</button>
        </div>
      </li>
    </ol>
    <p v-if="!shown.length" class="ws-empty">{{ rows.length ? 'Nothing matches these filters.' : 'No saved answers or thoughts in this run.' }}</p>
    <WorkspacePager v-if="shown.length > size" v-model:page="page" :size="size" :total="shown.length" label="responses" />
  </section>
</template>

<script setup>
// The Buyer responses tab: every survey answer, feed thought and saved thought, with an answer summary, filters by
// answer, source, segment and what held people back, search, and a way to ask that person a follow-up.
import { computed, ref, watch } from 'vue'
import { MessageCircle, Search, X } from 'lucide-vue-next'
import WorkspacePager from './WorkspacePager.vue'
import { SEGMENT_COLORS } from '../../workspace/geoPlace'
import { buildResponses, filterResponses, plainLabel, summarizeResponses } from '../../workspace/responses'

const props = defineProps({
  survey: { type: Object, default: null }, feed: { type: Object, default: null }, stream: { type: [Array, Object], default: null }, index: { type: Array, default: () => [] },
  // filters asked for from the chat ({ verdict, segment, objection, source, query }); the chips stay changeable
  initialFilters: { type: Object, default: null }
})
defineEmits(['ask'])

const start = props.initialFilters || {}
const pick = (v, allowed) => (allowed.includes(String(v || '').toLowerCase()) ? String(v).toLowerCase() : '')
const q = ref(String(start.query || '')), verdict = ref(pick(start.verdict, ['yes', 'maybe', 'no'])), source = ref(pick(start.source, ['survey', 'feed', 'thought']))
const segment = ref(''), objection = ref(String(start.objection || '').toLowerCase()), page = ref(0)
const size = 30
const verdictKeys = ['yes', 'maybe', 'no']
const verdictLabel = { yes: 'Would buy', maybe: 'Maybe', no: 'Would not' }
const sourceLabel = { survey: 'Survey', feed: 'Scrolling the feed', thought: 'Thought' }
const verdictChips = [{ id: 'yes', label: 'Would buy' }, { id: 'maybe', label: 'Maybe' }, { id: 'no', label: 'Would not' }]
const sourceChips = [{ id: 'survey', label: 'Survey' }, { id: 'feed', label: 'Feed' }, { id: 'thought', label: 'Thoughts' }]

const rows = computed(() => buildResponses({ survey: props.survey, feed: props.feed, stream: props.stream, index: props.index }))
const summary = computed(() => summarizeResponses(rows.value))
const segments = computed(() => summary.value.segments)
const segOrder = computed(() => [...new Set(props.index.map((p) => p.segment || 'Unspecified segment'))])
const colorOf = (seg) => SEGMENT_COLORS[Math.max(0, segOrder.value.indexOf(seg || 'Unspecified segment')) % SEGMENT_COLORS.length]
const shown = computed(() => filterResponses(rows.value, { verdict: verdict.value, source: source.value, segment: segment.value, objection: objection.value, q: q.value }))
const paged = computed(() => shown.value.slice(page.value * size, (page.value + 1) * size))
const filtered = computed(() => !!(q.value || verdict.value || source.value || segment.value || objection.value))
watch([q, verdict, source, segment, objection], () => { page.value = 0 })
// a segment asked for from the chat is matched to the run's own segment names once the answers load; otherwise it
// becomes a search, so nothing asked for is dropped
let seeded = !start.segment
watch(segments, (list) => {
  if (seeded || !list.length) return
  seeded = true
  const want = String(start.segment).toLowerCase()
  const hit = list.find((s) => String(s.key).toLowerCase() === want)
  if (hit) segment.value = hit.key
  else q.value = [q.value, start.segment].filter(Boolean).join(' ')
}, { immediate: true })

const pct = (n) => (summary.value.asked ? Math.round((100 * n) / summary.value.asked) : 0)
const initials = (name) => String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
const firstName = (name) => String(name || 'them').split(/\s+/)[0]
function clear() { q.value = ''; verdict.value = ''; source.value = ''; segment.value = ''; objection.value = '' }
</script>

<style scoped>
.br { display: grid; gap: 12px; min-width: 0; }
.br-summary { display: grid; gap: 8px; padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.br-bar { display: flex; height: 10px; border-radius: 6px; overflow: hidden; background: var(--line); }
.br-bar i { display: block; height: 100%; }
.br-bar i.yes, .br-dot.yes { background: #2f8f5b; }
.br-bar i.maybe, .br-dot.maybe { background: #c8962e; }
.br-bar i.no, .br-dot.no { background: #c2554d; }
.br-legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12.5px; }
.br-legend li { display: inline-flex; align-items: center; gap: 6px; }
.br-legend small, .br-sim { color: var(--muted); }
.br-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.br-tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.br-search { flex: 1 1 240px; display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--muted); }
.br-search:focus-within { outline: 2px solid var(--accent); outline-offset: 1px; }
.br-search input { flex: 1; min-width: 0; border: 0; background: none; color: var(--text); font: inherit; font-size: 13px; outline: none; }
.br-chips { display: inline-flex; flex-wrap: wrap; gap: 4px; }
.br-chips button, .br-reasons button { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 11px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; cursor: pointer; }
.br-chips button small, .br-reasons button small { color: var(--muted); }
.br-chips button[aria-pressed='true'], .br-reasons button[aria-pressed='true'] { background: var(--panel-2); border-color: var(--accent); font-weight: 600; }
.br-tools select { height: 36px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; padding: 0 8px; max-width: 100%; }
.br-reasons { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.br-reasons > span { font-size: 12px; color: var(--muted); margin-right: 2px; }
.br-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; }
.br-head p { margin: 0; font-size: 12.5px; }
.br-head small { color: var(--muted); }
.br-clear { display: inline-flex; align-items: center; gap: 5px; border: 0; background: none; color: var(--accent); font: inherit; font-size: 12.5px; cursor: pointer; }
.br-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.br-item { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 12px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.br-avatar { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-size: 12px; font-weight: 700; }
.br-body { min-width: 0; display: grid; gap: 4px; }
.br-body header { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; font-size: 13px; }
.br-body header small, .br-src { color: var(--muted); font-size: 11.5px; }
.br-pill { font-size: 11px; font-weight: 600; padding: 1px 8px; border-radius: 999px; border: 1px solid currentColor; }
.br-pill.yes { color: #2f8f5b; } .br-pill.maybe { color: #a87a1c; } .br-pill.no { color: #c2554d; }
.br-text { margin: 0; font-size: 13.5px; line-height: 1.5; overflow-wrap: anywhere; }
.br-meta { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.45; }
.br-meta b { color: var(--text); font-weight: 600; }
.br-ask { justify-self: start; display: inline-flex; align-items: center; gap: 6px; margin-top: 2px; border: 0; background: none; padding: 0; color: var(--accent); font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.br-ask:hover { text-decoration: underline; }
.br button:focus-visible, .br select:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
@media (max-width: 600px) { .br-chips button, .br-reasons button { height: 36px; } .br-item { grid-template-columns: 28px minmax(0, 1fr); gap: 10px; padding: 10px 12px; } .br-avatar { width: 28px; height: 28px; font-size: 11px; } }
</style>
