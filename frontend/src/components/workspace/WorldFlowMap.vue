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
      <div ref="el" class="wfm-map" :style="{ height: height + 'px' }" role="img" :aria-label="summary"></div>
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
      <li><b>{{ placed }}</b> of {{ people.length }} people on the map</li>
    </ul>

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
                <span class="wfm-c" role="img" :aria-label="`${t.replies} ${t.replies === 1 ? 'reply' : 'replies'}`"><MessageCircle :size="12" aria-hidden="true" />{{ t.replies }}</span>
                <span class="wfm-c" role="img" :aria-label="`${t.likes} ${t.likes === 1 ? 'like' : 'likes'}`"><Heart :size="12" aria-hidden="true" />{{ t.likes }}</span>
                <span class="wfm-c" role="img" :aria-label="`${t.quotes} ${t.quotes === 1 ? 'quote or share' : 'quotes and shares'}`"><Repeat2 :size="12" aria-hidden="true" />{{ t.quotes }}</span>
              </span>
            </div>
          </li>
        </ol>
      </div>
    </div>
    <p class="wfm-note">
      Simulated. Each dot is an invented person placed in their country; cities are not mapped, so dots inside a country are
      spread out for visibility. Lines show replies, likes, quotes and shares between people during the social rounds; a ring
      means they answered the brand. Select a dot or a post to open that person.
    </p>
  </section>
</template>

<script setup>
// The audience on a flat world map: Codex's bundled Natural Earth country shapes drawn with ECharts, every simulated
// person at their country, and who replied to, liked, quoted or shared whom in each social round, from feed_story.json.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Brain, Heart, MessageCircle, Pause, Play, Repeat2 } from 'lucide-vue-next'
import EChart from './EChart.vue'
import { countries } from '../../workspace/audienceGeography'
import { SEGMENT_COLORS, placeOfCountry, spread } from '../../workspace/geoPlace'
import { feedEdges, plainDid } from '../../workspace/runActivity'

const props = defineProps({
  index: { type: Array, default: () => [] },
  story: { type: Object, default: null },
  harvest: { type: Object, default: null },
  theme: { type: String, default: 'light' },
  live: Boolean,
  big: Boolean,
  height: { type: Number, default: 360 },
  selected: { type: String, default: '' }
})
const emit = defineEmits(['select'])
const el = ref(null), step = ref(0), playing = ref(false), scrubbed = ref(false)
const layers = reactive({ reply: true, like: true, quote: true })
let chart = null, echartsLib = null, timer = null, observer = null, framed = null, disposed = false
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

const positions = computed(() => {
  const counts = {}, centres = {}, out = {}
  for (const p of people.value) {
    const c = placeOfCountry(p.country)
    if (c) { const key = c.join(','); centres[p.agent_id] = c; counts[key] = (counts[key] || 0) + 1 }
  }
  for (const p of people.value) {
    const c = centres[p.agent_id]
    if (c) out[String(p.agent_id)] = spread(c, p.agent_id, counts[c.join(',')])
  }
  return out
})
const placed = computed(() => Object.keys(positions.value).length)
const summary = computed(() => `World map: ${placed.value} of ${people.value.length} simulated people placed in their countries. ${current.value?.label || ''}: ${stepEdges.value.length} interactions and ${stepThoughts.value.length} written posts or thoughts.`)

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

function frame() {
  // fit the first view to where the people are; afterwards keep the reader's pan and zoom
  if (framed) return {}
  const pts = Object.values(positions.value)
  if (!pts.length) return {}
  const lons = pts.map((x) => x[0]), lats = pts.map((x) => x[1]), pad = 8
  framed = { boundingCoords: [[Math.max(-180, Math.min(...lons) - pad), Math.min(85, Math.max(...lats) + pad)], [Math.min(180, Math.max(...lons) + pad), Math.max(-60, Math.min(...lats) - pad)]] }
  return framed
}
function option() {
  const dark = props.theme === 'dark', pos = positions.value
  const line = (e) => (pos[String(e.from)] && pos[String(e.to)] ? { coords: [pos[String(e.from)], pos[String(e.to)]], lineStyle: { color: kindColor[e.kind] } } : null)
  const seen = new Set()
  const pulses = current.value?.id === 'all' ? [] : stepEdges.value.filter((e) => e.toBrand && pos[String(e.from)] && !seen.has(e.from) && seen.add(e.from))
    .map((e) => ({ value: pos[String(e.from)], itemStyle: { color: kindColor[e.kind] } }))
  const active = activeIds.value
  const dots = people.value.filter((x) => pos[String(x.agent_id)]).map((x) => {
    const id = String(x.agent_id), on = !current.value || active.has(id), sel = props.selected === id
    return { id, name: x.name || `Person ${id}`, value: pos[id], segment: x.segment, country: x.country, symbolSize: sel ? 14 : on ? 9 : 5,
      itemStyle: { color: colorOf(x.segment), opacity: on || sel ? 1 : 0.35, borderColor: sel ? (dark ? '#fff0be' : '#383168') : 'transparent', borderWidth: sel ? 2 : 0 } }
  })
  return {
    backgroundColor: 'transparent', animationDurationUpdate: 400,
    tooltip: { trigger: 'item', confine: true, formatter: (x) => (x.seriesId === 'people' ? `<b>${esc(x.data.name)}</b><br>${esc([x.data.segment, x.data.country].filter(Boolean).join(' · '))}<br><i>Select to open</i>` : x.componentType === 'geo' ? esc(x.name) : '') },
    geo: {
      map: 'mm-world', roam: true, ...frame(), scaleLimit: { min: 0.8, max: 14 },
      itemStyle: { areaColor: dark ? '#1f2a33' : '#e3ebe8', borderColor: dark ? '#33424d' : '#c3cfc8', borderWidth: 0.6 },
      emphasis: { itemStyle: { areaColor: dark ? '#2b3a45' : '#d4e1db' }, label: { show: false } }, select: { disabled: true }, label: { show: false }
    },
    series: [
      { id: 'past', type: 'lines', coordinateSystem: 'geo', silent: true, zlevel: 1, lineStyle: { width: 0.8, opacity: 0.18, curveness: 0.25 }, data: pastEdges.value.map(line).filter(Boolean) },
      { id: 'now', type: 'lines', coordinateSystem: 'geo', silent: true, zlevel: 2, effect: { show: !reduced && current.value?.id !== 'all', period: 2.2, trailLength: 0.35, symbol: 'arrow', symbolSize: 6 },
        lineStyle: { width: 1.6, opacity: 0.75, curveness: 0.25 }, data: stepEdges.value.map(line).filter(Boolean) },
      { id: 'brand', type: 'effectScatter', coordinateSystem: 'geo', silent: true, zlevel: 2, symbolSize: 7, rippleEffect: { scale: reduced ? 1 : 2.4, brushType: 'stroke', number: 2 }, itemStyle: { opacity: 0.8 }, data: pulses },
      { id: 'people', type: 'scatter', coordinateSystem: 'geo', zlevel: 3, data: dots, cursor: 'pointer', emphasis: { scale: 1.6 } }
    ]
  }
}
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

async function render() {
  if (!el.value || disposed) return
  if (!echartsLib) {
    echartsLib = await import('echarts')
    if (!echartsLib.getMap('mm-world')) echartsLib.registerMap('mm-world', { type: 'FeatureCollection', features: countries })
  }
  if (disposed || !el.value) return
  if (!chart) {
    chart = echartsLib.init(el.value, null, { renderer: 'canvas' })
    chart.on('click', (x) => x.seriesId === 'people' && emit('select', String(x.data.id)))
  }
  chart.setOption(option(), { replaceMerge: ['series'] })
}

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
watch(() => [step.value, props.theme, props.selected, positions.value, layers.reply, layers.like, layers.quote, props.story, props.harvest], render)

onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(el.value)
})
onBeforeUnmount(() => {
  disposed = true
  clearInterval(timer)
  observer?.disconnect()
  chart?.dispose()
})
</script>

<style scoped>
.wfm { min-width: 0; }
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
