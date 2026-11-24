<template>
  <section class="wfm" :class="{ big, dark: theme === 'dark' }" aria-label="World map of simulated people and their social interactions">
    <div class="wfm-bar">
      <button type="button" class="wfm-icon" :aria-label="playing ? 'Pause the replay' : 'Play the run step by step'" :title="playing ? 'Pause' : 'Play'" :disabled="steps.length < 2" @click="toggle">
        <Pause v-if="playing" :size="16" /><Play v-else :size="16" />
      </button>
      <label class="wfm-slider"><span class="sr-only">Step</span>
        <input v-model.number="step" type="range" min="0" :max="Math.max(0, steps.length - 1)" step="1" :aria-valuetext="current?.label" @input="scrubbed = true; playing = false" />
      </label>
      <b class="wfm-step">{{ current?.label || 'No recorded activity' }}</b>
      <span v-if="live" class="wfm-live"><i aria-hidden="true"></i>Updating</span>
      <div class="wfm-layers" role="group" aria-label="Show interactions">
        <button v-for="k in kinds" :key="k.id" type="button" :aria-pressed="layers[k.id]" @click="layers[k.id] = !layers[k.id]"><i :style="{ background: k.color }" aria-hidden="true"></i>{{ k.label }}</button>
      </div>
    </div>
    <div class="wfm-body">
      <div class="wfm-mapcol">
        <RealWorldMap ref="mapRef" :points="mapPoints" :arcs="mapArcs" :pulses="mapPulses" :basemap="basemap" :globe="globe" :heat="heat"
          :cluster="people.length > 300" :mix-keys="legend.map((l) => ({ key: l.key, color: l.color }))" :theme="theme" :height="height" :label="summary" @select="(id) => $emit('select', id)">
          <template #overlay>
            <div class="gm-top">
              <div class="gm-search" role="combobox" :aria-expanded="!!suggestions.length" aria-haspopup="listbox" aria-owns="gm-suggest">
                <Search :size="15" aria-hidden="true" />
                <input v-model="query" type="search" placeholder="Search a person, city or segment" aria-label="Search the map" aria-autocomplete="list"
                  @keydown.down.prevent="moveHit(1)" @keydown.up.prevent="moveHit(-1)" @keydown.enter.prevent="pick(suggestions[hit] || suggestions[0])" @keydown.esc="query = ''" />
                <button v-if="query" type="button" class="gm-x" aria-label="Clear search" @click="query = ''"><X :size="14" /></button>
              </div>
              <button type="button" class="gm-chip" :aria-expanded="panelOpen" aria-controls="wfm-layers-panel" @click="panelOpen = !panelOpen"><SlidersHorizontal :size="14" aria-hidden="true" />{{ colorBy === 'verdict' ? 'By answer' : 'By segment' }}{{ heat ? ' · glow' : '' }}</button>
            </div>
            <ul v-if="suggestions.length" id="gm-suggest" class="gm-suggest" role="listbox" aria-label="Matches">
              <li v-for="(sg, i) in suggestions" :key="sg.kind + sg.id" role="option" :aria-selected="i === hit" :class="{ on: i === hit }" @mousedown.prevent="pick(sg)" @mouseenter="hit = i">
                <component :is="sg.kind === 'person' ? UserRound : sg.kind === 'place' ? MapPin : UsersRound" :size="15" aria-hidden="true" />
                <span><b>{{ sg.title }}</b><small>{{ sg.sub }}</small></span>
              </li>
            </ul>
            <div v-if="panelOpen" id="wfm-layers-panel" class="wfm-panel" role="group" aria-label="Colour and glow" @keydown.esc="panelOpen = false">
              <p>Colour people by</p>
              <div class="wfm-seg" role="group" aria-label="Colour people by">
                <button type="button" :aria-pressed="colorBy === 'segment'" @click="colorBy = 'segment'">Segment</button>
                <button type="button" :aria-pressed="colorBy === 'verdict'" :disabled="!hasVerdicts" :title="hasVerdicts ? 'Colour by their survey answer' : 'No survey answers in this run'" @click="colorBy = 'verdict'">Would buy</button>
              </div>
              <label class="wfm-switch"><input v-model="heat" type="checkbox" /><span>{{ hasVerdicts ? 'Glow where people said yes' : 'Glow where people are' }}</span></label>
            </div>
            <article v-else-if="selectedRow" class="gm-card" aria-label="Selected person">
              <header>
                <span class="gm-dot" :style="{ background: pointColor(selectedRow) }" aria-hidden="true"></span>
                <div><h4>{{ selectedRow.name || `Person ${selected}` }}</h4><small>{{ [selectedRow.segment, selectedPlace].filter(Boolean).join(' · ') }}</small></div>
                <button type="button" class="gm-x" aria-label="Close" @click="$emit('select', '')"><X :size="15" /></button>
              </header>
              <p v-if="selectedVerdict" class="gm-verdict" :class="selectedVerdict">Would buy: {{ { yes: 'yes', maybe: 'maybe', no: 'no' }[selectedVerdict] }} <small>simulated</small></p>
              <blockquote v-if="selectedQuote">“{{ selectedQuote }}”</blockquote>
              <div class="gm-actions">
                <button type="button" @click="zoomToSelected"><Navigation :size="14" aria-hidden="true" />Zoom here</button>
                <button type="button" @click="$emit('profile', selected)"><IdCard :size="14" aria-hidden="true" />Full profile</button>
              </div>
            </article>
          </template>
          <template #corner>
            <div v-if="basemapList.length > 1" class="gm-types" :class="{ open: typesOpen }" @mouseleave="typesOpen = false">
              <button type="button" class="gm-tile" :class="altType.id" :aria-label="`Switch to ${altType.label}`" :title="`Switch to ${altType.label}`" @click="basemap = altType.id" @mouseenter="typesOpen = true" @focus="typesOpen = true">
                <span>{{ altType.label }}</span>
              </button>
              <div v-if="typesOpen" class="gm-more" role="group" aria-label="More map types">
                <button v-for="b in basemapList" :key="b.id" type="button" class="gm-tile small" :class="b.id" :aria-pressed="basemap === b.id" @click="basemap = b.id"><span>{{ b.label }}</span></button>
                <button type="button" class="gm-tile small globe" :aria-pressed="globe" @click="globe = !globe"><span>Globe</span></button>
              </div>
            </div>
          </template>
        </RealWorldMap>
        <div class="wfm-legend" aria-label="Colour key">
          <span v-for="l in legend" :key="l.label"><i :style="{ background: l.color }" aria-hidden="true"></i>{{ l.label }}</span>
        </div>
      </div>
      <aside class="wfm-feed" aria-label="What people wrote at this step">
        <h5><Brain :size="14" aria-hidden="true" />{{ feedTitle }} <small>simulated</small></h5>
        <ol>
          <li v-for="(t, i) in stepThoughts" :key="i" :class="{ account: t.account }" :style="{ '--seg': t.account ? 'var(--line)' : t.color }">
            <button type="button" :disabled="!!t.account" :title="t.account ? t.account : `Open ${t.who}`" @click="$emit('select', String(t.agent_id))">
              <b>{{ t.who }}</b><small>{{ [t.account || t.segment, t.country].filter(Boolean).join(' · ') }}</small>
              <span class="wfm-kind" :class="t.kind">{{ t.kindLabel }}</span>{{ t.text }}
              <em v-if="t.did">{{ t.did }}</em>
            </button>
          </li>
        </ol>
        <p v-if="!stepThoughts.length" class="wfm-note">Nothing written at this step.</p>
      </aside>
    </div>

    <ul class="wfm-stats" aria-label="At this step">
      <li><b>{{ count('reply') }}</b> replies</li>
      <li><b>{{ count('like') }}</b> likes</li>
      <li><b>{{ count('quote') }}</b> quotes and shares</li>
      <li><b>{{ activeIds.size }}</b> people active</li>
      <li><b>{{ atCity }}</b> of {{ people.length }} people at their city<span v-if="placed > atCity">, {{ placed - atCity }} near their country's centre</span></li>
    </ul>

    <div v-if="places.length" class="wfm-places">
      <h5><MapPin :size="14" aria-hidden="true" />Places <small>select one to fly there</small></h5>
      <ul>
        <li v-for="pl in places" :key="pl.key">
          <button type="button" @click="mapRef?.flyTo(pl.lon, pl.lat, pl.city ? 8 : 4)">
            <b>{{ pl.label }}</b>
            <span>{{ pl.n }} {{ plural(pl.n, { one: 'person', other: 'people' }) }}</span>
            <span v-if="pl.asked" class="wfm-yes" :title="`${pl.yes} of ${pl.asked} said yes (simulated)`"><i :style="{ width: Math.round(100 * pl.yes / pl.asked) + '%' }"></i></span>
            <small v-if="pl.asked">{{ pl.yes }} of {{ pl.asked }} yes</small>
          </button>
        </li>
      </ul>
    </div>

    <div v-if="edges.length" class="wfm-extra">
      <div class="wfm-box">
        <h5>Interactions per round <small>simulated</small></h5>
        <EChart :option="perRound" :height="big ? 220 : 180" :theme="theme" label="Replies, likes, quotes and shares in each social round" />
      </div>
      <div class="wfm-box">
        <h5>Most discussed posts <small>simulated</small></h5>
        <ol class="wfm-top">
          <li v-for="(t, i) in topPosts" :key="i">
            <span class="wfm-rank">{{ i + 1 }}</span>
            <div>
              <b>{{ t.who }}</b><small>{{ t.where }}</small>
              <p>{{ t.text }}</p>
              <span class="wfm-n">
                <span class="wfm-c" role="img" :aria-label="`${t.replies} ${plural(t.replies, { one: 'reply', other: 'replies' })}`"><MessageCircle :size="12" aria-hidden="true" />{{ t.replies }}</span>
                <span class="wfm-c" role="img" :aria-label="`${t.likes} ${plural(t.likes, { one: 'like', other: 'likes' })}`"><Heart :size="12" aria-hidden="true" />{{ t.likes }}</span>
                <span class="wfm-c" role="img" :aria-label="`${t.quotes} ${plural(t.quotes, { one: 'quote or share', other: 'quotes and shares' })}`"><Repeat2 :size="12" aria-hidden="true" />{{ t.quotes }}</span>
              </span>
            </div>
          </li>
        </ol>
      </div>
    </div>
    <p class="wfm-note">
      Simulated. Each dot is an invented person at the city saved in their profile (towns of 5,000+ people from GeoNames);
      people whose city is not found sit near their country's centre. Arcs show replies, likes, quotes and shares between
      people during the social rounds; a ring means they answered the brand. Select a dot or a post to open that person.
      Street maps © OpenStreetMap via OpenFreeMap; satellite imagery NASA Blue Marble; the Simple map works offline.
    </p>
  </section>
</template>

<script setup>
// The audience on a flat world map: Codex's bundled Natural Earth country shapes drawn with ECharts, every simulated
// person at their country, and who replied to, liked, quoted or shared whom in each social round, from feed_story.json.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Brain, Heart, IdCard, Layers, Map as MapIcon, MapPin, MessageCircle, Moon, Navigation, Pause, Play, Repeat2, Satellite, Search, SlidersHorizontal, UserRound, UsersRound, X } from 'lucide-vue-next'
import EChart from './EChart.vue'
import RealWorldMap from './RealWorldMap.vue'
import { SEGMENT_COLORS, placeOfCountry } from '../../workspace/geoPlace'
import { findCity, jitter, loadGazetteer } from '../../workspace/cityPlace'
import { availableBasemaps, loadMapConfig } from '../../workspace/mapConfig'
import { feedEdges, plainDid } from '../../workspace/runActivity'
import { plural } from '../../workspace/plural.js'

const props = defineProps({
  index: { type: Array, default: () => [] },
  story: { type: Object, default: null },
  harvest: { type: Object, default: null },
  responses: { type: Array, default: () => [] },
  theme: { type: String, default: 'light' },
  live: Boolean,
  big: Boolean,
  height: { type: Number, default: 360 },
  selected: { type: String, default: '' }
})
const emit = defineEmits(['select', 'profile'])
const mapRef = ref(null), step = ref(0), playing = ref(false), scrubbed = ref(false), gazetteer = ref(null)
const layers = reactive({ reply: true, like: true, quote: true })
const pref = (k, d) => { try { return localStorage.getItem(k) || d } catch { return d } }
const panelOpen = ref(false), typesOpen = ref(false), query = ref(''), hit = ref(0)
const basemap = ref(pref('mm-map-style', 'auto')), globe = ref(pref('mm-map-globe', '') === '1'), colorBy = ref('segment'), heat = ref(false)
watch(basemap, (v) => { try { localStorage.setItem('mm-map-style', v) } catch { /* private window */ } })
watch(globe, (v) => { try { localStorage.setItem('mm-map-globe', v ? '1' : '') } catch { /* private window */ } })
const basemaps = [
  { id: 'auto', label: 'Streets', icon: MapIcon, hint: 'Street map that follows light or dark mode (OpenStreetMap)' },
  { id: 'satellite', label: 'Satellite', icon: Satellite, hint: 'NASA Blue Marble imagery' },
  { id: 'dark', label: 'Night', icon: Moon, hint: 'Dark street map' },
  { id: 'simple', label: 'Simple', icon: Layers, hint: 'Country shapes only; works offline' }
]
let timer = null
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

const people = computed(() => props.index.filter((r) => (r.kind || 'persona') === 'persona'))
const allById = computed(() => Object.fromEntries(props.index.map((r) => [String(r.agent_id), r])))
const segments = computed(() => [...new Set(people.value.map((p) => p.segment || 'Unspecified segment'))])
const colorOf = (seg) => SEGMENT_COLORS[Math.max(0, segments.value.indexOf(seg || 'Unspecified segment')) % SEGMENT_COLORS.length]
const kinds = [{ id: 'reply', label: 'Replies', color: '#507cba' }, { id: 'like', label: 'Likes', color: '#2f8f5b' }, { id: 'quote', label: 'Quotes and shares', color: '#d0558f' }]
const kindColor = Object.fromEntries(kinds.map((k) => [k.id, k.color]))

const edges = computed(() => feedEdges(props.story))
const roundOf = (t) => { const m = String(t.context || '').match(/round (\d+)/i); return m ? Number(m[1]) : null }
const thoughts = computed(() => (props.harvest?.entries || []).filter((t) => t.text).map((t) => {
  const r = t.source === 'social feed' ? roundOf(t) : null
  return { ...t, round: r, phase: r !== null ? 'round' : /survey|pitch/i.test(t.source || '') ? 'after' : 'before' }
}))
const rounds = computed(() => [...new Set([...edges.value.map((e) => e.round), ...thoughts.value.map((t) => t.round)].filter((r) => r !== null && r !== undefined))].sort((a, b) => a - b))
const steps = computed(() => {
  const out = []
  if (thoughts.value.some((t) => t.phase === 'before')) out.push({ id: 'before', label: 'Before the rounds: ads and landing page' })
  for (const r of rounds.value) out.push({ id: `r${r}`, round: r, label: `Social round ${r} of ${rounds.value[rounds.value.length - 1]}` })
  if (thoughts.value.some((t) => t.phase === 'after')) out.push({ id: 'after', label: 'After: survey and sales pitch' })
  if (edges.value.length) out.push({ id: 'all', label: 'All social activity, every round' })
  return out
})
const current = computed(() => steps.value[step.value] || null)
const inStep = (x) => {
  const c = current.value
  if (!c) return false
  if (c.id === 'before') return x.phase === 'before'
  if (c.id === 'after') return x.phase === 'after'
  if (c.id === 'all') return x.phase === 'round'
  return x.round === c.round
}
const stepEdges = computed(() => {
  const c = current.value
  if (c?.id === 'all') return edges.value.filter((e) => layers[e.kind])
  return c?.round === undefined ? [] : edges.value.filter((e) => e.round === c.round && layers[e.kind])
})
const pastEdges = computed(() => (current.value?.round === undefined ? [] : edges.value.filter((e) => e.round !== null && e.round < current.value.round && layers[e.kind])))
const count = (k) => stepEdges.value.filter((e) => e.kind === k).length
const stepThoughts = computed(() => thoughts.value.filter(inStep).slice(0, 40).map((t) => {
  const p = allById.value[String(t.agent_id)] || {}
  const account = p.kind && p.kind !== 'persona' ? (p.kind === 'community' ? 'Community account' : 'Brand account') : ''
  return { agent_id: t.agent_id, account, who: t.name || p.name || `Person ${t.agent_id}`, segment: t.segment || p.segment, country: account ? '' : p.country,
    text: t.text, did: plainDid(t.did), kind: t.kind, kindLabel: { private_thought: 'thought', said: 'said', posted: 'posted' }[t.kind] || t.kind, color: colorOf(t.segment || p.segment) }
}))
const activeIds = computed(() => new Set([...stepEdges.value.map((e) => String(e.from)), ...stepThoughts.value.filter((t) => !t.account).map((t) => String(t.agent_id))]))
const feedTitle = computed(() => ({ before: 'Thinking while scrolling', after: 'What they said afterwards', all: 'Everything written in the rounds' })[current.value?.id] || 'Written this round')

const VERDICT_COLORS = { yes: '#2f8f5b', maybe: '#c8962e', no: '#c2554d', none: '#8a8f94' }
const verdictById = computed(() => {
  const out = {}
  for (const r of props.responses || []) {
    const v = String(r?.answer?.would_convert || '').toLowerCase()
    if (r && r.agent_id !== undefined && v) out[String(r.agent_id)] = /^(yes|maybe|no)$/.test(v) ? v : 'maybe'
  }
  return out
})
const hasVerdicts = computed(() => Object.keys(verdictById.value).length > 0)
// each person at their city when the gazetteer knows it, otherwise spread around their country's centre
const located = computed(() => {
  const idx = gazetteer.value, found = {}, centres = {}, counts = {}, out = {}
  for (const p of people.value) {
    const id = String(p.agent_id)
    const city = idx ? findCity(idx, p.city, p.country) : null
    const at = city ? [city[0], city[1]] : placeOfCountry(p.country)
    if (!at) continue
    const key = `${city ? 'c' : 'k'}:${at.join(',')}`
    ;(city ? found : centres)[id] = { at, key, city: city?.[2] || '' }
    counts[key] = (counts[key] || 0) + 1
  }
  for (const [id, v] of Object.entries(found)) out[id] = { pos: jitter(v.at, id, counts[v.key]), city: v.city, exact: true, key: v.key, at: v.at }
  for (const [id, v] of Object.entries(centres)) out[id] = { pos: jitter(v.at, id, counts[v.key], true), city: '', exact: false, key: v.key, at: v.at }
  return out
})
const positions = computed(() => Object.fromEntries(Object.entries(located.value).map(([id, v]) => [id, v.pos])))
const placed = computed(() => Object.keys(positions.value).length)
const atCity = computed(() => Object.values(located.value).filter((v) => v.exact).length)
const places = computed(() => {
  const groups = {}
  for (const p of people.value) {
    const l = located.value[String(p.agent_id)]
    if (!l) continue
    const g = (groups[l.key] ||= { key: l.key, lon: l.at[0], lat: l.at[1], city: l.city, label: l.exact ? `${l.city}, ${p.country}` : `${p.country} (city not found)`, n: 0, yes: 0, asked: 0 })
    g.n++
    const v = verdictById.value[String(p.agent_id)]
    if (v) { g.asked++; if (v === 'yes') g.yes++ }
  }
  return Object.values(groups).sort((a, b) => b.n - a.n).slice(0, 12)
})
const pointColor = (p) => (colorBy.value === 'verdict' ? VERDICT_COLORS[verdictById.value[String(p.agent_id)] || 'none'] : colorOf(p.segment))
const legend = computed(() => (colorBy.value === 'verdict'
  ? [{ key: 'yes', label: 'Would buy', color: VERDICT_COLORS.yes }, { key: 'maybe', label: 'Maybe', color: VERDICT_COLORS.maybe }, { key: 'no', label: 'Would not', color: VERDICT_COLORS.no }, { key: 'none', label: 'Not asked', color: VERDICT_COLORS.none }]
  : segments.value.slice(0, 8).map((seg) => ({ key: seg, label: seg, color: colorOf(seg) }))))
const mapCfg = ref(null)
const basemapList = computed(() => { const ok = availableBasemaps(mapCfg.value || undefined); return basemaps.filter((b) => ok.includes(b.id)) })
const altType = computed(() => {
  const list = basemapList.value, sat = list.find((b) => b.id === 'satellite')
  return basemap.value === 'satellite' || !sat ? list.find((b) => b.id !== basemap.value) || list[0] : sat
})
// search like a maps app: people by name, places by city, segments
const suggestions = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (q.length < 2) return []
  const out = []
  for (const p of people.value) {
    if (out.length >= 5) break
    if (String(p.name || '').toLowerCase().includes(q)) out.push({ kind: 'person', id: String(p.agent_id), title: p.name, sub: [p.segment, located.value[String(p.agent_id)]?.city || p.country].filter(Boolean).join(' · ') })
  }
  for (const pl of places.value) if (out.length < 8 && pl.label.toLowerCase().includes(q)) out.push({ kind: 'place', id: pl.key, title: pl.label, sub: `${pl.n} ${plural(pl.n, { one: 'person', other: 'people' })}`, at: [pl.lon, pl.lat], city: !!pl.city })
  for (const seg of segments.value) if (out.length < 10 && seg.toLowerCase().includes(q)) out.push({ kind: 'segment', id: seg, title: seg, sub: `${people.value.filter((p) => (p.segment || 'Unspecified segment') === seg).length} people · colour by segment` })
  return out
})
watch(query, () => { hit.value = 0 })
function moveHit(d) { const n = suggestions.value.length; if (n) hit.value = (hit.value + d + n) % n }
function pick(sg) {
  if (!sg) return
  query.value = ''
  if (sg.kind === 'person') { emit('select', sg.id); const pos = positions.value[sg.id]; if (pos) mapRef.value?.flyTo(pos[0], pos[1], 9) }
  else if (sg.kind === 'place') mapRef.value?.flyTo(sg.at[0], sg.at[1], sg.city ? 9 : 4)
  else colorBy.value = 'segment'
}
const selectedRow = computed(() => people.value.find((p) => String(p.agent_id) === props.selected) || null)
const selectedPlace = computed(() => { const l = located.value[props.selected]; return l ? (l.exact ? `${l.city}, ${selectedRow.value?.country}` : selectedRow.value?.country) : selectedRow.value?.country })
const selectedVerdict = computed(() => verdictById.value[props.selected] || '')
const selectedQuote = computed(() => {
  const r = (props.responses || []).find((x) => String(x.agent_id) === props.selected)
  const t = r?.answer?.reason || r?.answer?.why || r?.answer?.quote || thoughts.value.find((x) => String(x.agent_id) === props.selected)?.text || ''
  return String(t).slice(0, 180)
})
function zoomToSelected() { const pos = positions.value[props.selected]; if (pos) mapRef.value?.flyTo(pos[0], pos[1], 10) }
const layerSummary = computed(() => [basemaps.find((b) => b.id === basemap.value)?.label, globe.value ? 'globe' : '', colorBy.value === 'verdict' ? 'by answer' : 'by segment', heat.value ? 'glow' : ''].filter(Boolean).join(' · '))
const mapPoints = computed(() => {
  const active = activeIds.value, pos = positions.value
  return people.value.filter((x) => pos[String(x.agent_id)]).map((x) => {
    const id = String(x.agent_id), l = located.value[id], v = verdictById.value[id]
    return { id, lon: pos[id][0], lat: pos[id][1], color: pointColor(x), title: x.name || `Person ${id}`,
      sub: [x.segment, l?.exact ? `${l.city}, ${x.country}` : x.country, v ? `would buy: ${v} (simulated)` : ''].filter(Boolean).join(' · '),
      mix: colorBy.value === 'verdict' ? (v || 'none') : (x.segment || 'Unspecified segment'), size: 5, dim: !!current.value && !active.has(id) && props.selected !== id, selected: props.selected === id,
      weight: hasVerdicts.value ? ({ yes: 1, maybe: 0.4, no: 0.05 })[v] ?? 0.1 : 1 }
  })
})
const mapArcs = computed(() => {
  const pos = positions.value
  const arc = (e, past) => (pos[String(e.from)] && pos[String(e.to)] ? { from: pos[String(e.from)], to: pos[String(e.to)], color: kindColor[e.kind], past } : null)
  return [...pastEdges.value.map((e) => arc(e, true)), ...stepEdges.value.map((e) => arc(e, false))].filter(Boolean)
})
const mapPulses = computed(() => {
  if (current.value?.id === 'all') return []
  const pos = positions.value, seen = new Set()
  return stepEdges.value.filter((e) => e.toBrand && pos[String(e.from)] && !seen.has(e.from) && seen.add(e.from))
    .map((e) => ({ lon: pos[String(e.from)][0], lat: pos[String(e.from)][1], color: kindColor[e.kind] }))
})
const summary = computed(() => `World map: ${atCity.value} of ${people.value.length} simulated people at their city, ${placed.value - atCity.value} near their country's centre. ${current.value?.label || ''}: ${stepEdges.value.length} interactions and ${stepThoughts.value.length} written posts or thoughts.`)

const perRound = computed(() => {
  const dark = props.theme === 'dark', muted = dark ? '#b0b3b8' : '#686e73', line = dark ? '#303237' : '#e8ebe9'
  const rs = rounds.value
  return {
    animation: !reduced, textStyle: { fontFamily: 'inherit', color: dark ? '#ececec' : '#17181a' },
    grid: { left: 4, right: 10, top: 28, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true },
    legend: { top: 0, textStyle: { color: muted, fontSize: 11 } },
    xAxis: { type: 'category', data: rs.map((r) => `R${r}`), axisLabel: { color: muted }, axisLine: { lineStyle: { color: line } } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
    series: kinds.map((k) => ({ name: k.label, type: 'bar', stack: 'all', data: rs.map((r) => edges.value.filter((e) => e.kind === k.id && e.round === r).length), itemStyle: { color: k.color } }))
  }
})
const topPosts = computed(() => {
  const list = []
  for (const [platform, pl] of Object.entries(props.story?.platforms || {})) {
    for (const post of pl.posts || []) {
      const a = post.author || {}, replies = (post.comments || []).length, likes = post.likes || (post.likers || []).length || 0, quotes = (post.quotes || []).length
      list.push({ who: a.name || 'Someone', text: String(post.content || '').slice(0, 160), replies, likes, quotes, score: replies * 3 + quotes * 2 + likes,
        where: [{ twitter: 'Twitter-style', reddit: 'Reddit-style' }[platform] || platform, post.round !== undefined ? `round ${post.round}` : '', a.kind === 'persona' ? '' : a.kind === 'community' ? 'community' : 'brand'].filter(Boolean).join(' · ') })
    }
  }
  return list.sort((x, y) => y.score - x.score).slice(0, 5)
})

function toggle() {
  playing.value = !playing.value
  if (playing.value && step.value >= steps.value.length - 1) step.value = 0
}
watch(playing, (v) => {
  clearInterval(timer)
  if (v) timer = setInterval(() => { if (step.value >= steps.value.length - 1) playing.value = false; else step.value++ }, reduced ? 3500 : 2400)
})
// open on everything; a live run follows the newest round unless the reader moved the slider
watch(() => steps.value.length, (n, old) => {
  if (props.live && !scrubbed.value) step.value = Math.max(0, n - 1 - (steps.value[n - 1]?.id === 'all' ? 1 : 0))
  else if (!old && n) step.value = n - 1
}, { immediate: true })

onMounted(async () => { loadMapConfig().then((c) => { mapCfg.value = c }); gazetteer.value = await loadGazetteer() })
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.wfm { min-width: 0; }
.gm-top { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.gm-search { display: flex; align-items: center; gap: 8px; width: min(340px, calc(100vw - 120px)); background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 0 10px 0 14px; height: 40px; box-shadow: 0 2px 12px rgba(0,0,0,.16); color: var(--muted); }
.gm-search:focus-within { outline: 2px solid var(--accent, #25785d); outline-offset: 1px; }
.gm-search input { flex: 1; min-width: 0; border: 0; background: none; color: var(--text); font: inherit; font-size: 13.5px; outline: none; }
.gm-search input::-webkit-search-cancel-button { display: none; }
.gm-x { display: grid; place-items: center; width: 26px; height: 26px; border: 0; border-radius: 50%; background: none; color: var(--muted); cursor: pointer; }
.gm-x:hover { background: var(--panel-2); color: var(--text); }
.gm-chip { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 12px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--text); font: inherit; font-size: 12.5px; cursor: pointer; box-shadow: 0 2px 10px rgba(0,0,0,.12); }
.gm-chip[aria-expanded='true'] { background: var(--panel-2); }
.gm-chip:focus-visible, .gm-actions button:focus-visible, .gm-tile:focus-visible { outline: 2px solid var(--accent, #25785d); outline-offset: 1px; }
.gm-suggest { list-style: none; margin: 6px 0 0; padding: 6px; width: min(340px, calc(100vw - 120px)); background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 10px 30px rgba(0,0,0,.2); max-height: 300px; overflow-y: auto; }
.gm-suggest li { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 9px; cursor: pointer; color: var(--muted); }
.gm-suggest li.on { background: var(--panel-2); }
.gm-suggest span { display: grid; min-width: 0; }
.gm-suggest b { color: var(--text); font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gm-suggest small { font-size: 11.5px; }
.gm-card { margin-top: 8px; width: min(320px, calc(100vw - 120px)); background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; box-shadow: 0 10px 30px rgba(0,0,0,.2); display: grid; gap: 8px; animation: gm-in .18s ease-out; }
@media (prefers-reduced-motion: reduce) { .gm-card { animation: none; } }
@keyframes gm-in { from { opacity: 0; transform: translateY(-4px); } }
.gm-card header { display: flex; gap: 10px; align-items: flex-start; }
.gm-card header > div { flex: 1; min-width: 0; }
.gm-card h4 { margin: 0; font-size: 15px; }
.gm-card header small { color: var(--muted); font-size: 12px; }
.gm-dot { width: 12px; height: 12px; border-radius: 50%; margin-top: 4px; flex: none; }
.gm-verdict { margin: 0; font-size: 12.5px; font-weight: 600; }
.gm-verdict.yes { color: #2f8f5b; } .gm-verdict.maybe { color: #b07f1c; } .gm-verdict.no { color: #c2554d; }
.gm-verdict small { font-weight: 400; color: var(--muted); margin-left: 4px; }
.gm-card blockquote { margin: 0; font-size: 12.5px; line-height: 1.45; color: var(--text); border-left: 3px solid var(--line); padding-left: 9px; }
.gm-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.gm-actions button { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 12px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); color: var(--accent, #25785d); font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.gm-actions button:hover { background: var(--panel-2); }
.gm-types { display: flex; align-items: flex-end; gap: 8px; }
.gm-more { display: flex; gap: 6px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 6px; box-shadow: 0 6px 20px rgba(0,0,0,.18); }
.gm-tile { position: relative; width: 72px; height: 72px; border-radius: 12px; border: 2px solid #fff; box-shadow: 0 2px 10px rgba(0,0,0,.3); cursor: pointer; overflow: hidden; padding: 0; background-size: cover; background-position: center; }
.gm-tile.small { width: 52px; height: 52px; border-width: 1px; border-color: var(--line); box-shadow: none; }
.gm-tile.small[aria-pressed='true'] { border: 2px solid var(--accent, #25785d); }
.gm-tile span { position: absolute; left: 0; right: 0; bottom: 0; padding: 3px 4px; font-size: 10.5px; font-weight: 600; color: #fff; background: linear-gradient(transparent, rgba(0,0,0,.6)); text-align: left; }
.gm-tile.satellite { background-image: url('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/2/1/2.jpeg'); background-color: #1d3b5a; }
.gm-tile.auto { background: linear-gradient(135deg, #e8efe9 0 40%, #cfe3f1 40% 55%, #f2efe6 55%), #e8efe9; }
.gm-tile.auto::before { content: ''; position: absolute; inset: 0; background: linear-gradient(20deg, transparent 46%, #f6c66b 46% 50%, transparent 50%), linear-gradient(110deg, transparent 60%, #fff 60% 64%, transparent 64%); }
.gm-tile.dark { background: linear-gradient(135deg, #1f2328 0 45%, #2b3a4a 45% 60%, #262a30 60%); }
.gm-tile.dark::before { content: ''; position: absolute; inset: 0; background: linear-gradient(20deg, transparent 46%, #5c6b7a 46% 49%, transparent 49%); }
.gm-tile.simple { background: radial-gradient(circle at 35% 45%, #cfdcd4 0 28%, transparent 29%), radial-gradient(circle at 70% 60%, #cfdcd4 0 20%, transparent 21%), #eef3f6; }
.gm-tile.globe { background: radial-gradient(circle at 40% 35%, #6fa3c9, #1d3b5a 70%); }
.gm-tile.globe[aria-pressed='true'] { border: 2px solid var(--accent, #25785d); }
@media (max-width: 600px) {
  .gm-tile { width: 56px; height: 56px; }
  .gm-more { flex-wrap: wrap; max-width: 190px; }
  .gm-search { width: calc(100vw - 96px); }
  .gm-suggest { width: calc(100vw - 96px); }
  /* the place card becomes a bottom sheet, as in maps apps */
  .gm-card { position: fixed; left: 8px; right: 8px; bottom: 8px; width: auto; z-index: 60; border-radius: 16px 16px 14px 14px; box-shadow: 0 -6px 30px rgba(0,0,0,.25); animation-name: gm-up; }
  .gm-card::before { content: ''; justify-self: center; width: 36px; height: 4px; border-radius: 4px; background: var(--line); margin: -4px 0 2px; }
}
@keyframes gm-up { from { opacity: 0; transform: translateY(16px); } }
.wfm-layers-btn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); border-radius: 9px; background: var(--panel); color: var(--text); font: inherit; font-size: 12px; font-weight: 600; padding: 6px 10px; cursor: pointer; box-shadow: 0 2px 10px rgba(0,0,0,.12); max-width: 100%; }
.wfm-layers-sum { font-weight: 400; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wfm-layers-btn:focus-visible, .wfm-switch input:focus-visible { outline: 2px solid var(--accent, #25785d); outline-offset: 1px; }
.wfm-panel { margin-top: 6px; width: min(290px, calc(100vw - 80px)); background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px 12px; box-shadow: 0 10px 30px rgba(0,0,0,.18); display: grid; gap: 8px; }
.wfm-panel p { margin: 4px 0 0; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
.wfm-seg-wrap { flex-wrap: wrap; }
.wfm-switch { display: flex; align-items: center; gap: 8px; font-size: 12.5px; cursor: pointer; }
.wfm-switch input { accent-color: var(--accent, #25785d); width: 15px; height: 15px; }
.wfm-seg { display: inline-flex; border: 1px solid var(--line); border-radius: 9px; overflow: hidden; background: var(--panel); }
.wfm-seg button, .wfm-chip { display: inline-flex; align-items: center; gap: 5px; border: 0; background: none; color: var(--text); font: inherit; font-size: 11.5px; padding: 5px 9px; cursor: pointer; }
.wfm-seg button + button { border-left: 1px solid var(--line); }
.wfm-seg button[aria-pressed='true'], .wfm-chip[aria-pressed='true'] { background: var(--panel-2); font-weight: 600; box-shadow: inset 0 -2px 0 var(--accent, #25785d); }
.wfm-seg button:disabled { opacity: .45; cursor: not-allowed; }
.wfm-chip { border: 1px solid var(--line); border-radius: 9px; background: var(--panel); }
.wfm-seg button:focus-visible, .wfm-chip:focus-visible, .wfm-places button:focus-visible { outline: 2px solid var(--accent, #25785d); outline-offset: 1px; }
.wfm-mapcol { min-width: 0; display: grid; gap: 6px; }
.wfm-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--muted); }
.wfm-legend span { display: inline-flex; align-items: center; gap: 5px; }
.wfm-legend i { width: 8px; height: 8px; border-radius: 50%; }
.wfm-places { margin-top: 12px; }
.wfm-places h5 { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--muted); margin: 0 0 6px; }
.wfm-places h5 small { margin-left: auto; font-weight: 400; }
.wfm-places ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 6px; }
.wfm-places button { width: 100%; display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 2px 8px; text-align: left; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--text); font: inherit; font-size: 12px; padding: 7px 10px; cursor: pointer; }
.wfm-places button:hover { background: var(--panel-2); }
.wfm-places button b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wfm-places button > span:not(.wfm-yes) { color: var(--muted); font-size: 11px; }
.wfm-places small { color: var(--muted); font-size: 10.5px; }
.wfm-yes { height: 4px; border-radius: 4px; background: var(--line); overflow: hidden; }
.wfm-yes i { display: block; height: 100%; background: #2f8f5b; }
.wfm-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
.wfm-icon { display: grid; place-items: center; width: 32px; height: 32px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--text); cursor: pointer; }
.wfm-icon:disabled { opacity: .4; cursor: not-allowed; }
.wfm-slider { flex: 1; min-width: 120px; display: flex; }
.wfm-slider input { width: 100%; accent-color: var(--accent, #25785d); }
.wfm-step { font-size: 12px; font-weight: 600; flex-basis: 100%; order: 5; }
.wfm.big .wfm-step { flex-basis: auto; order: 0; }
.wfm-live { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted); }
.wfm-live i { width: 7px; height: 7px; border-radius: 50%; background: #e0782f; animation: wfm-pulse 1.4s ease-in-out infinite; }
.wfm-layers { display: flex; flex-wrap: wrap; gap: 4px; }
.wfm-layers button { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px; padding: 3px 10px; font-size: 11.5px; cursor: pointer; }
.wfm-layers button[aria-pressed='false'] { opacity: .5; }
.wfm-layers i { width: 8px; height: 8px; border-radius: 50%; }
.wfm-body { display: grid; gap: 10px; }
.wfm.big .wfm-body { grid-template-columns: minmax(0, 1fr) 300px; }
.wfm-map { width: 100%; border: 1px solid var(--line); border-radius: 12px; background: var(--panel-2); overflow: hidden; }
.wfm-feed { border: 1px solid var(--line); border-radius: 12px; padding: 10px; max-height: 260px; overflow-y: auto; }
.wfm.big .wfm-feed { max-height: 520px; }
.wfm-feed h5, .wfm-box h5 { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--muted); margin: 0 0 6px; }
.wfm-feed h5 small, .wfm-box h5 small { margin-left: auto; font-weight: 400; }
.wfm-feed ol, .wfm-top { list-style: none; margin: 0; padding: 0; }
.wfm-feed li { margin-bottom: 6px; border-left: 3px solid var(--seg, var(--line)); border-radius: 4px; }
.wfm-feed li button { display: block; width: 100%; text-align: left; border: 0; background: none; color: var(--text); font: inherit; font-size: 12.5px; line-height: 1.45; padding: 7px 8px 7px 10px; border-radius: 4px; cursor: pointer; }
.wfm-feed li button:hover:not(:disabled) { background: var(--panel-2); }
.wfm-feed li button:disabled { cursor: default; opacity: .85; }
.wfm-feed li b { margin-right: 6px; }
.wfm-feed li small { display: block; color: var(--muted); font-size: 11px; margin-bottom: 2px; }
.wfm-feed li em { display: block; font-style: normal; color: var(--muted); font-size: 11px; margin-top: 3px; }
.wfm-kind { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); border: 1px solid var(--line); border-radius: 5px; padding: 0 5px; margin-right: 5px; }
.wfm-kind.posted { color: var(--text); border-color: var(--line); }
.wfm-kind.private_thought { color: #25785d; border-color: #25785d; }
.wfm.dark .wfm-kind.private_thought { color: #8fd6b5; border-color: #8fd6b5; }
.wfm-stats { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.wfm-stats li { font-size: 11.5px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; }
.wfm-stats b { color: var(--text); }
.wfm-extra { display: grid; gap: 10px; margin-top: 12px; }
.wfm.big .wfm-extra { grid-template-columns: 1fr 1fr; }
.wfm-box { border: 1px solid var(--line); border-radius: 12px; padding: 12px; min-width: 0; }
.wfm-top li { display: flex; gap: 10px; padding: 8px 0; border-top: 1px solid var(--line); font-size: 12.5px; }
.wfm-top li:first-child { border-top: 0; }
.wfm-top small { margin-left: 6px; color: var(--muted); font-size: 11px; }
.wfm-top p { margin: 3px 0; color: var(--muted); overflow-wrap: anywhere; }
.wfm-rank { width: 22px; height: 22px; flex: none; border-radius: 7px; display: grid; place-items: center; border: 1px solid var(--line); background: var(--panel-2); font-size: 11px; font-weight: 600; }
.wfm-n { display: inline-flex; flex-wrap: wrap; align-items: center; color: var(--muted); font-size: 11.5px; }
.wfm-c { display: inline-flex; align-items: center; gap: 3px; margin-right: 12px; }
.wfm-note { font-size: 11px; line-height: 1.7; color: var(--muted); margin: 10px 0 0; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@keyframes wfm-pulse { 50% { opacity: .3; } }
@media (prefers-reduced-motion: reduce) { .wfm-live i { animation: none; } }
@media (max-width: 760px) { .wfm.big .wfm-body, .wfm.big .wfm-extra { grid-template-columns: 1fr; } }
</style>
