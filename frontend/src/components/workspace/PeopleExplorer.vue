<template>
  <section class="pe" :class="{ 'pe-compact': compact }" :aria-labelledby="`${uid}-title`">
    <header ref="head" class="pe-head">
      <div>
        <h3 :id="`${uid}-title`">People in this run</h3>
        <p class="pe-note">Every invented person in the run, read from the saved files. Browsing is free: no model calls.</p>
      </div>
      <button v-if="rows.length" type="button" class="pe-btn" :disabled="!filtered.length" @click="downloadCsv">
        <Download :size="15" aria-hidden="true" />Download CSV<span class="sr-only"> of the {{ filtered.length }} people shown, simulated</span>
      </button>
    </header>

    <LoadingSkeleton v-if="busy" variant="cards" :lines="4" label="Loading the simulated people" />
    <p v-else-if="error" class="pe-error" role="alert">{{ error }} <button type="button" class="pe-link" @click="load">Try again</button></p>
    <p v-else-if="!rows.length" class="pe-empty">No simulated people were saved in this run. Runs made from a seed document alone have accounts, not buyers.</p>

    <template v-else>
      <div class="pe-toolbar">
        <label class="pe-search">
          <Search :size="15" aria-hidden="true" />
          <span class="sr-only">Search people by name, city, job or words in their answer</span>
          <input v-model="query" type="search" placeholder="Search name, city, job or their words" autocomplete="off" />
        </label>
        <label class="pe-sort">
          <span>Sort</span>
          <select v-model="sort" aria-label="Sort people">
            <option v-for="s in SORTS" :key="s.id" :value="s.id">{{ s.label }}</option>
          </select>
        </label>
        <button type="button" class="pe-btn" :aria-expanded="filtersOpen" :aria-controls="`${uid}-filters`" @click="filtersOpen = !filtersOpen">
          <SlidersHorizontal :size="15" aria-hidden="true" />Filters<span v-if="chipCount" class="pe-badge">{{ chipCount }}<span class="sr-only"> active</span></span>
        </button>
      </div>

      <div v-show="filtersOpen" :id="`${uid}-filters`" class="pe-filters">
        <fieldset v-for="f in shownFacets" :key="f.id" class="pe-facet" :class="{ 'pe-facet-wide': options[f.id].length > 4 }">
          <legend>{{ f.label }}</legend>
          <div class="pe-chips">
            <button v-for="o in options[f.id]" :key="o.value" type="button" :aria-pressed="filters[f.id].includes(o.value)" :class="f.id === 'verdict' ? `pe-v-${o.value}` : ''" @click="toggle(f.id, o.value)">
              {{ o.label }}<span class="pe-chip-n">{{ fmt(o.count) }}</span>
            </button>
          </div>
        </fieldset>
      </div>

      <div class="pe-count">
        <p role="status" aria-live="polite"><b>{{ fmt(filtered.length) }}</b> of {{ fmt(rows.length) }} simulated people<template v-if="activeCount"> match</template></p>
        <button v-if="activeCount" type="button" class="pe-link" @click="clearFilters"><X :size="13" aria-hidden="true" />Clear filters</button>
      </div>

      <section v-if="filtered.length" class="pe-summary" :aria-label="`Summary of the ${filtered.length} people shown, simulated`">
        <p class="pe-summary-head">For the people shown <span class="pe-sim">Simulated</span></p>
        <dl>
          <div><dt>People shown</dt><dd><b>{{ fmt(summary.people) }}</b></dd></div>
          <div>
            <dt>Say they would buy</dt>
            <dd><b>{{ summary.buyText }}</b><small v-if="summary.asked">{{ fmt(summary.maybe) }} maybe · {{ fmt(summary.no) }} no · n = {{ fmt(summary.asked) }}</small></dd>
          </div>
          <div>
            <dt>Top objection</dt>
            <dd v-if="summary.topObjection"><b>{{ summary.topObjection.label }}</b><small>{{ fmt(summary.topObjection.count) }} people ({{ summary.topObjection.pct }}% of those asked)</small></dd>
            <dd v-else><b>None saved</b></dd>
          </div>
          <div>
            <dt>Top jobs</dt>
            <dd v-if="summary.topOccupations.length"><span v-for="j in summary.topOccupations" :key="j.label" class="pe-job-line">{{ j.label }} <small>{{ fmt(j.count) }}</small></span></dd>
            <dd v-else><b>Not saved</b></dd>
          </div>
        </dl>
      </section>

      <p v-if="!filtered.length" class="pe-empty">Nobody matches these filters. <button type="button" class="pe-link" @click="clearFilters">Clear filters</button></p>

      <WorkspacePager v-if="filtered.length > pageSize" v-model:page="page" :size="pageSize" :total="filtered.length" label="people" />
      <ul v-if="filtered.length" class="pe-grid" aria-label="Simulated people">
        <li v-for="r in paged" :key="r.id" class="pe-card" :class="{ picked: picked.includes(r.id) }">
          <button type="button" class="pe-open" :aria-label="cardLabel(r)" :aria-describedby="`${uid}-why-${r.id}`" @click="openPerson(r, $event)">
            <span class="pe-top">
              <span class="pe-avatar" :style="{ background: r.color }" aria-hidden="true">{{ r.initials }}</span>
              <span class="pe-who">
                <span class="pe-name">{{ r.name }}</span>
                <span class="pe-meta">{{ [r.age, [r.city, r.country].filter(Boolean).join(', ')].filter(Boolean).join(' · ') }}</span>
                <span v-if="r.occupation" class="pe-occ">{{ r.occupation }}</span>
              </span>
            </span>
            <span class="pe-verdict" :class="r.verdict">{{ VERDICT_LABEL[r.verdict] }}<small>simulated</small></span>
            <span v-if="r.why" :id="`${uid}-why-${r.id}`" class="pe-why"><span class="pe-why-src">{{ r.whySource }}:</span> {{ r.why }}</span>
            <span v-else :id="`${uid}-why-${r.id}`" class="pe-why pe-muted">No answer saved.</span>
          </button>
          <label class="pe-pick">
            <input type="checkbox" :checked="picked.includes(r.id)" :disabled="!picked.includes(r.id) && picked.length >= MAX_COMPARE" @change="pick(r.id)" />
            <span>Compare<span class="sr-only"> {{ r.name }}</span></span>
          </label>
        </li>
      </ul>
      <WorkspacePager v-if="filtered.length > pageSize" v-model:page="page" :size="pageSize" :total="filtered.length" label="people" />
      <p class="pe-note pe-foot"><ShieldCheck :size="13" aria-hidden="true" />Invented people. Every answer was written by an AI model playing them, so read the numbers as directions, not measurements.</p>

      <div v-if="picked.length" class="pe-compare-bar" role="region" aria-label="People picked to compare">
        <span><b>{{ picked.length }}</b> of {{ MAX_COMPARE }} picked</span>
        <span class="pe-compare-names">{{ pickedRows.map((r) => r.name).join(', ') }}</span>
        <button type="button" class="pe-btn pe-primary" :disabled="pickedRows.length < 2" @click="openCompare($event)"><GitCompare :size="15" aria-hidden="true" />Compare</button>
        <button type="button" class="pe-link" @click="picked = []">Clear</button>
      </div>
    </template>

    <Dialog v-model:open="sheetOpen">
      <DialogContent class="ws-overlay pe-sheet" :data-theme="theme" @close-auto-focus="onCloseFocus">
        <DialogHeader class="sr-only">
          <DialogTitle>{{ current?.name || 'Simulated person' }}</DialogTitle>
          <DialogDescription>Profile of an invented person from this run, with their saved answer and what they did.</DialogDescription>
        </DialogHeader>
        <div v-if="current" class="pe-sheet-body">
          <AudiencePersonCard v-bind="cardProps" />
          <section v-if="currentDecision.length" class="pe-bde" aria-label="Decision card">
            <h5>Decision card</h5>
            <dl><div v-for="d in currentDecision" :key="d.label"><dt>{{ d.label }}</dt><dd>{{ d.value }}</dd></div></dl>
          </section>
          <div class="pe-sheet-actions">
            <button type="button" class="pe-ask" @click="ask(current)"><MessageCircle :size="15" aria-hidden="true" />Ask this person<span class="pe-paid" aria-hidden="true">$</span></button>
            <label class="pe-pick">
              <input type="checkbox" :checked="picked.includes(current.id)" :disabled="!picked.includes(current.id) && picked.length >= MAX_COMPARE" @change="pick(current.id)" />
              <span>Add to comparison</span>
            </label>
          </div>
          <p class="pe-note">{{ askNote }}</p>
        </div>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="compareOpen">
      <DialogContent class="ws-overlay pe-compare" :data-theme="theme" @close-auto-focus="onCloseFocus">
        <DialogHeader class="pe-compare-head">
          <DialogTitle>Compare {{ pickedRows.length }} simulated people</DialogTitle>
          <DialogDescription>From the saved answers and activity. Each answer was written by a model playing an invented person.</DialogDescription>
        </DialogHeader>
        <div class="pe-compare-body">
          <table class="pe-cmp" :style="{ '--n': pickedRows.length }">
            <thead>
              <tr>
                <th scope="col" class="pe-cmp-corner"><span class="sr-only">Field</span></th>
                <th v-for="r in pickedRows" :key="r.id" scope="col">
                  <span class="pe-cmp-person">
                    <span class="pe-avatar" :style="{ background: r.color }" aria-hidden="true">{{ r.initials }}</span>
                    <span><b>{{ r.name }}</b><small>{{ r.segment }}</small></span>
                  </span>
                  <span class="pe-cmp-actions">
                    <button type="button" class="pe-link" @click="ask(r)"><MessageCircle :size="13" aria-hidden="true" />Ask<span class="sr-only"> {{ r.name }}</span><span class="pe-paid" aria-hidden="true">$</span></button>
                    <button type="button" class="pe-link" @click="pick(r.id)">Remove<span class="sr-only"> {{ r.name }}</span></button>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in comparison" :key="row.label">
                <th scope="row">{{ row.label }}</th>
                <td v-for="(v, i) in row.values" :key="i" :data-person="pickedRows[i]?.name">
                  <span class="pe-cmp-who" aria-hidden="true">{{ pickedRows[i]?.name }}</span>{{ v || 'Not saved' }}
                </td>
              </tr>
            </tbody>
          </table>
          <p class="pe-note">{{ askNote }}</p>
        </div>
      </DialogContent>
    </Dialog>
  </section>
</template>

<script setup>
// Browse every simulated person in a saved run: search, filter chips, sort, a summary of the people shown, a person
// sheet with the plain-language card, a side-by-side comparison of up to three people and a CSV of the filtered list.
// Everything comes from saved files; "Ask this person" hands over to the existing person chat, which asks first.
import { computed, nextTick, ref, useId, watch } from 'vue'
import { Download, GitCompare, MessageCircle, Search, ShieldCheck, SlidersHorizontal, X } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../ui/dialog'
import LoadingSkeleton from './LoadingSkeleton.vue'
import WorkspacePager from './WorkspacePager.vue'
import AudiencePersonCard from './AudiencePersonCard.vue'
import { api } from '../../workspace/api.js'
import { SEGMENT_COLORS } from '../../workspace/geoPlace.js'
import { feedEdges } from '../../workspace/runActivity.js'
import {
  FACETS, MAX_COMPARE, SORTS, VERDICT_LABEL, activeFilterCount, buildPeople, compareRows, csvFileName, decisionCard, emptyFilters,
  facetOptions, filterPeople, peopleCsv, peopleSummary, seedFilters, sortPeople, toggleCompare, toggleValue
} from '../../workspace/peopleExplorer.js'

const props = defineProps({
  name: { type: String, required: true },
  theme: { type: String, default: 'light' },
  compact: { type: Boolean, default: false },
  // the run page already holds these files; the chat card leaves them out and the explorer reads them itself
  preloaded: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  config: { type: Object, default: null },
  survey: { type: Object, default: null },
  stats: { type: [Array, Object], default: null },
  story: { type: Object, default: null },
  // filters asked for from the chat ("the people in Kenya"): applied once the people load, then freely changeable
  initialFilters: { type: Object, default: null }
})
const emit = defineEmits(['ask'])
const uid = useId()
const fmt = (n) => Number(n || 0).toLocaleString('en-US')
const askNote = 'Asking sends one model call to your provider. It opens the person chat first: nothing is sent until you press send and approve it.'

const own = ref({ config: null, survey: null, stats: null, story: null }), thoughts = ref([])
const fetching = ref(false), error = ref('')
let ticket = 0
async function load() {
  const mine = ++ticket
  error.value = ''
  const enc = encodeURIComponent(props.name)
  const harvest = api(`/api/runs/${enc}/thoughts`).then((h) => (Array.isArray(h?.entries) ? h.entries : [])).catch(() => [])
  if (props.preloaded) {
    const entries = await harvest
    if (mine === ticket) thoughts.value = entries
    return
  }
  fetching.value = true
  try {
    const run = await api(`/api/runs/${enc}`)
    const has = new Set(run.files || [])
    const read = (f) => (has.has(f) ? api(`/api/runs/${enc}/files/${f}`) : Promise.resolve(null))
    const [config, survey, stats, story, entries] = await Promise.all([read('config.json'), read('survey.json'), read('agent_stats.json').catch(() => null), read('feed_story.json').catch(() => null), harvest])
    if (mine !== ticket) return
    own.value = { config, survey, stats, story }
    thoughts.value = entries
  } catch (e) {
    if (mine === ticket) error.value = e.message || 'Could not read the saved people.'
  } finally {
    if (mine === ticket) fetching.value = false
  }
}
const src = computed(() => (props.preloaded ? { config: props.config, survey: props.survey, stats: props.stats, story: props.story } : own.value))
const busy = computed(() => (props.preloaded ? props.loading && !props.config : fetching.value))
const index = computed(() => src.value.config?.persona_index || [])
const rows = computed(() => buildPeople({ index: index.value, survey: src.value.survey, stats: src.value.stats, thoughts: thoughts.value, colors: SEGMENT_COLORS }))
const byId = computed(() => new Map(rows.value.map((r) => [r.id, r])))
const names = computed(() => Object.fromEntries(index.value.map((p) => [String(p.agent_id), p.name])))
const edges = computed(() => feedEdges(src.value.story))

// search, filters and sort
const query = ref(''), sort = ref('name'), filters = ref(emptyFilters())
const phone = typeof matchMedia === 'function' && matchMedia('(max-width: 600px)').matches
const filtersOpen = ref(!props.compact && !phone)
const options = computed(() => facetOptions(rows.value))
// a group with a single value filters nothing; it stays visible while it is selected so it can be cleared
const shownFacets = computed(() => FACETS.filter((f) => options.value[f.id].length > 1 || filters.value[f.id].length))
const filtered = computed(() => sortPeople(filterPeople(rows.value, { ...filters.value, query: query.value }), sort.value))
const activeCount = computed(() => activeFilterCount({ ...filters.value, query: query.value }))
const chipCount = computed(() => activeFilterCount(filters.value))
function toggle(facet, value) { filters.value = { ...filters.value, [facet]: toggleValue(filters.value[facet], value) } }
function clearFilters() { filters.value = emptyFilters(); query.value = '' }
let seeded = false
watch(() => rows.value.length, (n) => {
  if (seeded || !n || !props.initialFilters || !Object.keys(props.initialFilters).length) return
  seeded = true
  const { query: q, ...facets } = seedFilters(rows.value, props.initialFilters)
  filters.value = { ...emptyFilters(), ...facets }
  query.value = q
  if (activeFilterCount(facets)) filtersOpen.value = true
}, { immediate: true })
const summary = computed(() => peopleSummary(filtered.value))

// pages: 1,000+ people would be too many cards at once
const pageSize = computed(() => (props.compact ? 12 : 36))
const page = ref(0)
watch([query, sort, filters], () => { page.value = 0 })
watch(() => filtered.value.length, (n) => { page.value = Math.min(page.value, Math.max(0, Math.ceil(n / pageSize.value) - 1)) })
const head = ref(null)
watch(page, () => nextTick(() => head.value?.scrollIntoView({ block: 'nearest' })))
const paged = computed(() => filtered.value.slice(page.value * pageSize.value, (page.value + 1) * pageSize.value))
const cardLabel = (r) => `${r.name}${r.age ? `, ${r.age}` : ''}${r.city ? `, ${r.city}` : ''}, ${r.country}. ${VERDICT_LABEL[r.verdict]}, simulated. Open profile`

// person sheet and comparison
const sheetOpen = ref(false), compareOpen = ref(false), currentId = ref(''), picked = ref([])
let asking = false
const current = computed(() => byId.value.get(currentId.value) || null)
const pickedRows = computed(() => picked.value.map((id) => byId.value.get(id)).filter(Boolean))
const comparison = computed(() => compareRows(pickedRows.value))
const currentDecision = computed(() => decisionCard(current.value?.bde))
const cardProps = computed(() => {
  const r = current.value
  const id = r.id
  return {
    person: r.person, answer: r.answer, color: r.color, stats: r.stats, names: names.value,
    thoughts: thoughts.value.filter((t) => String(t.agent_id) === id && t.text && !(r.answer && t.source === 'survey')),
    edges: edges.value.filter((e) => String(e.from) === id || String(e.to) === id)
  }
})
function openPerson(r) { currentId.value = r.id; sheetOpen.value = true }
function pick(id) { picked.value = toggleCompare(picked.value, id) }
watch(() => pickedRows.value.length, (n) => { if (n < 2) compareOpen.value = false })
function openCompare() { sheetOpen.value = false; compareOpen.value = true }
// handing over to the person chat: close the dialog without pulling focus back to the card
function ask(r) {
  if (!r) return
  asking = true
  sheetOpen.value = false; compareOpen.value = false
  emit('ask', { id: r.id, name: r.name, segment: r.segment })
}
function onCloseFocus(event) { if (asking) { event.preventDefault(); asking = false } }

function downloadCsv() {
  const blob = new Blob([peopleCsv(filtered.value)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: csvFileName(props.name, filtered.value.length !== rows.value.length) })
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch(() => props.name, (now, before) => {
  if (before !== undefined) { picked.value = []; clearFilters(); sheetOpen.value = compareOpen.value = false }
  load()
}, { immediate: true })
</script>

<style scoped>
.pe { position: relative; min-width: 0; font-size: 13px; color: var(--text); }
.pe-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; scroll-margin-top: 12px; }
.pe-head h3 { margin: 0; font-size: 16px; font-weight: 600; letter-spacing: -.1px; }
.pe-compact .pe-head h3 { font-size: 14px; }
.pe-note { margin: 3px 0 0; font-size: 12px; line-height: 1.55; color: var(--muted); }
.pe-error, .pe-empty { margin: 14px 0 0; padding: 18px; border: 1px dashed var(--line); border-radius: 12px; color: var(--muted); font-size: 12.5px; line-height: 1.6; text-align: center; }
.pe-btn { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 6px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; font-weight: 500; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.pe-btn:hover:not(:disabled) { background: var(--panel-2); }
.pe-btn:disabled { opacity: .5; cursor: not-allowed; }
.pe-btn svg { color: var(--muted); }
.pe-primary { background: var(--text); color: var(--panel); border-color: var(--text); }
.pe-primary:hover:not(:disabled) { background: var(--text); opacity: .9; }
.pe-primary svg { color: inherit; }
.pe-badge { min-width: 18px; padding: 0 5px; border-radius: 999px; background: var(--accent-2); color: var(--accent); font-size: 11px; font-weight: 650; text-align: center; }
.pe-link { display: inline-flex; align-items: center; gap: 4px; padding: 0; border: 0; background: none; color: var(--accent); font: inherit; font-size: 12.5px; font-weight: 550; cursor: pointer; text-underline-offset: 3px; }
.pe-link:hover { text-decoration: underline; }
.pe-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 14px; }
.pe-search { flex: 1 1 260px; min-width: 0; display: flex; align-items: center; gap: 8px; min-height: 38px; padding: 0 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--muted); }
.pe-search:focus-within { border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); }
.pe-search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text); font: inherit; font-size: 13px; padding: 8px 0; }
.pe-sort { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
.pe-sort select { min-height: 36px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; padding: 6px 8px; }
.pe-filters { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px 18px; margin-top: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel-2); }
.pe-facet { margin: 0; padding: 0; border: 0; min-width: 0; }
.pe-facet-wide { grid-column: 1 / -1; }
.pe-facet legend { padding: 0; margin-bottom: 6px; font-size: 11px; font-weight: 600; color: var(--muted); }
.pe-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.pe-chips button { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; max-width: 100%; padding: 4px 11px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--text); font: inherit; font-size: 12px; cursor: pointer; text-align: left; overflow-wrap: anywhere; }
.pe-chips button:hover { border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); }
.pe-chips button[aria-pressed='true'] { border-color: color-mix(in srgb, var(--accent) 60%, var(--line)); background: var(--accent-2); font-weight: 550; }
.pe-chip-n { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
.pe-count { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-top: 14px; }
.pe-count p { margin: 0; font-size: 12.5px; color: var(--muted); }
.pe-count b { color: var(--text); font-variant-numeric: tabular-nums; }
.pe-summary { position: relative; margin-top: 10px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
.pe-summary-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 0 0 8px; font-size: 11px; font-weight: 600; color: var(--muted); }
.pe-sim { font-weight: 500; font-size: 10.5px; color: var(--warm); border: 1px solid color-mix(in srgb, var(--warm) 45%, var(--line)); border-radius: 999px; padding: 0 7px; }
.pe-summary dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px 16px; margin: 0; }
.pe-summary dl > div { min-width: 0; }
.pe-summary dt { font-size: 11px; color: var(--muted); margin-bottom: 2px; }
.pe-summary dd { margin: 0; display: grid; gap: 1px; min-width: 0; overflow-wrap: anywhere; }
.pe-summary dd b { font-size: 14px; font-weight: 650; font-variant-numeric: tabular-nums; }
.pe-summary dd small { font-size: 11.5px; color: var(--muted); }
.pe-job-line { font-size: 12.5px; line-height: 1.45; }
.pe-job-line small { color: var(--muted); font-variant-numeric: tabular-nums; }
.pe-grid { list-style: none; margin: 12px 0 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.pe-compact .pe-grid { grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
.pe-card { position: relative; display: flex; flex-direction: column; min-width: 0; border: 1px solid var(--line); border-radius: 13px; background: var(--panel); transition: border-color .15s, box-shadow .15s; }
.pe-card:hover { border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); box-shadow: 0 2px 10px rgb(40 40 70 / 6%); }
.pe-card.picked { border-color: color-mix(in srgb, var(--accent) 65%, var(--line)); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent); }
.pe-open { display: flex; flex: 1; flex-direction: column; gap: 9px; width: 100%; padding: 13px 13px 8px; border: 0; border-radius: 13px 13px 0 0; background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; min-width: 0; }
.pe-open:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.pe-top { display: flex; gap: 10px; align-items: flex-start; min-width: 0; }
.pe-avatar { flex: 0 0 38px; width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; color: #fff; font-size: 13px; font-weight: 650; letter-spacing: .3px; }
.pe-who { display: grid; gap: 1px; min-width: 0; }
.pe-name { font-size: 13.5px; font-weight: 600; line-height: 1.35; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pe-meta, .pe-occ { font-size: 12px; line-height: 1.4; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pe-occ { color: var(--text); }
.pe-verdict { align-self: flex-start; display: inline-flex; align-items: baseline; gap: 5px; padding: 1px 9px; border: 1px solid var(--line); border-radius: 999px; font-size: 11.5px; font-weight: 600; line-height: 1.7; }
.pe-verdict small { font-size: 10px; font-weight: 500; color: var(--muted); }
.pe-verdict.yes, .pe-v-yes[aria-pressed='true'] { color: var(--yes); border-color: color-mix(in srgb, var(--yes) 45%, var(--line)); }
.pe-verdict.maybe, .pe-v-maybe[aria-pressed='true'] { color: var(--maybe); border-color: color-mix(in srgb, var(--maybe) 50%, var(--line)); }
.pe-verdict.no, .pe-v-no[aria-pressed='true'] { color: var(--no); border-color: color-mix(in srgb, var(--no) 45%, var(--line)); }
.pe-verdict.none { color: var(--muted); border-style: dashed; }
.pe-why { font-size: 12.5px; line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
.pe-why-src { color: var(--muted); }
.pe-muted { color: var(--muted); }
.pe-pick { display: inline-flex; align-items: center; gap: 7px; min-height: 36px; padding: 0 13px 6px; font-size: 12px; color: var(--muted); cursor: pointer; align-self: flex-start; }
.pe-pick input { width: 16px; height: 16px; accent-color: var(--accent); cursor: pointer; }
.pe-pick input:disabled + span { opacity: .55; }
.pe-pick:has(input:disabled) { cursor: not-allowed; }
.pe-foot { display: flex; gap: 6px; align-items: flex-start; margin-top: 4px; font-size: 11.5px; }
.pe-compare-bar { position: sticky; bottom: 8px; z-index: 2; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-top: 12px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--line)); border-radius: 13px; background: var(--panel); box-shadow: 0 6px 24px rgb(30 30 60 / 14%); font-size: 12.5px; }
.pe-compare-names { flex: 1 1 160px; min-width: 0; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pe-sheet-body { min-width: 0; }
.pe-sheet-body :deep(.apc) { margin-top: 0; border: 0; padding: 0; background: transparent; }
.pe-bde { margin-top: 14px; padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel-2); }
.pe-bde h5 { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: var(--muted); }
.pe-bde dl { display: grid; gap: 6px; margin: 0; }
.pe-bde dt { font-size: 11px; color: var(--muted); }
.pe-bde dd { margin: 0; font-size: 12.5px; overflow-wrap: anywhere; }
.pe-sheet-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); }
.pe-sheet-actions .pe-pick { padding: 0; }
.pe-ask { display: inline-flex; align-items: center; gap: 7px; min-height: 38px; padding: 8px 14px; border: 0; border-radius: 10px; background: var(--text); color: var(--panel); font: inherit; font-size: 13px; font-weight: 550; cursor: pointer; }
.pe-ask:hover { opacity: .9; }
.pe-paid { margin-left: 2px; font-weight: 700; color: var(--warm, #a55c32); }
.pe-compare-head { padding: 18px 22px 12px; border-bottom: 1px solid var(--line); }
.pe-compare-body { min-height: 0; overflow: auto; padding: 4px 22px 18px; }
.pe-cmp { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12.5px; line-height: 1.5; }
.pe-cmp th, .pe-cmp td { padding: 9px 10px; border: 0; border-top: 1px solid var(--line); background: none; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.pe-cmp thead th { border-top: 0; position: sticky; top: 0; background: var(--panel); z-index: 1; }
.pe-cmp-corner { width: 150px; }
.pe-cmp tbody th { font-size: 11.5px; font-weight: 600; color: var(--muted); }
.pe-cmp-person { display: flex; gap: 8px; align-items: center; min-width: 0; }
.pe-cmp-person b { display: block; font-size: 13px; font-weight: 600; }
.pe-cmp-person small { display: block; font-size: 11px; font-weight: 400; color: var(--muted); }
.pe-cmp-person .pe-avatar { flex-basis: 32px; width: 32px; height: 32px; font-size: 12px; border-radius: 9px; }
.pe-cmp-actions { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 6px; }
.pe-cmp-actions .pe-link { min-height: 30px; font-size: 12px; }
.pe-cmp-who { display: none; }
@media (max-width: 600px) {
  .pe-compare-head { padding: 16px 16px 10px; }
  .pe-compare-body { padding: 4px 14px 16px; }
  .pe-cmp, .pe-cmp thead, .pe-cmp tbody { display: block; }
  .pe-cmp tr { display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: 0 8px; border-top: 1px solid var(--line); padding: 8px 0; }
  .pe-cmp thead tr { border-top: 0; position: sticky; top: 0; background: var(--panel); z-index: 1; }
  .pe-cmp th, .pe-cmp td { display: block; border-top: 0; padding: 2px 0; }
  .pe-cmp thead th { position: static; }
  .pe-cmp-corner { display: none !important; }
  .pe-cmp tbody th { grid-column: 1 / -1; padding-bottom: 4px; }
  .pe-cmp-person { flex-direction: column; align-items: flex-start; gap: 4px; }
  .pe-cmp-who { display: block; font-size: 10.5px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 600px) {
  .pe-head { flex-direction: column; }
  .pe-toolbar { gap: 6px; }
  .pe-search { flex-basis: 100%; min-height: 44px; }
  .pe-sort { flex: 1; }
  .pe-sort select { flex: 1; min-height: 44px; }
  .pe-btn { min-height: 44px; }
  .pe-chips button { min-height: 38px; }
  .pe-summary dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pe-grid, .pe-compact .pe-grid { grid-template-columns: 1fr; }
  .pe-pick { min-height: 44px; }
}
@media (prefers-reduced-motion: reduce) { .pe-card { transition: none; } }
</style>
