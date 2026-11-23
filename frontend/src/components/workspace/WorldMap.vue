<template>
  <section class="ws-world" :class="{ big }" aria-label="World map of simulated people and their interactions">
    <div class="ws-world-bar">
      <button type="button" class="ws-icon-btn bordered" :aria-label="playing ? 'Pause the replay' : 'Play the run step by step'" :title="playing ? 'Pause' : 'Play'" :disabled="steps.length < 2" @click="toggle">
        <Ico :name="playing ? 'pause' : 'play'" />
      </button>
      <label class="ws-world-slider">
        <span class="sr-only">Step</span>
        <input v-model.number="step" type="range" min="0" :max="Math.max(0, steps.length - 1)" step="1" :aria-valuetext="steps[step]?.label" @input="scrubbed = true; playing = false" />
      </label>
      <b class="ws-world-step">{{ steps[step]?.label || 'No activity' }}</b>
      <span v-if="live" class="ws-tagx warm"><span class="ws-live-dot" aria-hidden="true"></span>Live</span>
      <div class="ws-world-layers" role="group" aria-label="Show interactions">
        <button v-for="k in kinds" :key="k.id" type="button" class="ws-chip" :aria-pressed="layers[k.id]" @click="layers[k.id] = !layers[k.id]">
          <i :style="{ background: k.color }" aria-hidden="true"></i>{{ k.label }}
        </button>
      </div>
      <button v-if="!big" type="button" class="ws-icon-btn" title="Full screen" aria-label="Open the world map full screen" @click="$emit('expand')"><Ico name="external" /></button>
    </div>

    <div class="ws-world-body">
      <div ref="el" class="ws-world-map" :style="{ height: height + 'px' }" role="img" :aria-label="summary"></div>
      <aside class="ws-world-feed" aria-label="What people were thinking at this step">
        <h4><Ico name="brain" :size="14" />{{ feedTitle }}</h4>
        <ol role="log" aria-live="off">
          <li v-for="(t, i) in stepThoughts" :key="i" :class="{ account: t.account }" :style="{ '--seg': t.account ? 'var(--line)' : t.color }" @click="$emit('select', t.agent_id)">
            <b>{{ t.who }}</b><small>{{ [t.segment, t.country].filter(Boolean).join(' · ') }}</small>
            <span class="ws-kind" :class="t.kind">{{ t.kindLabel }}</span>{{ t.text }}
            <em v-if="t.did">{{ t.did }}</em>
          </li>
        </ol>
        <p v-if="!stepThoughts.length" class="ws-note">Nothing written at this step.</p>
      </aside>
    </div>

    <ul class="ws-world-stats" aria-label="This step">
      <li><b>{{ stepEdges.filter((e) => e.kind === 'reply').length }}</b> replies</li>
      <li><b>{{ stepEdges.filter((e) => e.kind === 'like').length }}</b> likes</li>
      <li><b>{{ stepEdges.filter((e) => e.kind === 'quote').length }}</b> quotes and shares</li>
      <li><b>{{ activeIds.size }}</b> people active</li>
      <li><b>{{ placed }}</b> of {{ people.length }} people on the map</li>
    </ul>
    <div v-if="edges.length" class="ws-world-extra">
      <div class="ws-box">
        <h4>Interactions per round <small>simulated</small></h4>
        <EChart :option="perRound" :height="big ? 220 : 180" label="Replies, likes and quotes in each social round" :theme="theme" />
      </div>
      <div class="ws-box">
        <h4>Most discussed posts <small>simulated</small></h4>
        <ol class="ws-top-posts">
          <li v-for="(t, i) in topPosts" :key="i" @click="t.person && $emit('select', t.agentId)">
            <span class="ws-top-rank">{{ i + 1 }}</span>
            <div>
              <b>{{ t.who }}</b><small>{{ t.where }}</small>
              <p>{{ t.text }}</p>
              <span class="ws-top-n"><Ico name="chat" :size="12" />{{ t.replies }} <Ico name="star" :size="12" />{{ t.likes }} <Ico name="refresh" :size="12" />{{ t.quotes }}</span>
            </div>
          </li>
        </ol>
      </div>
    </div>
    <p class="ws-note">
      Simulated. Each dot is an invented person, placed in their country; cities are not mapped, so dots inside a country
      are spread out for visibility. Lines show replies, likes and quotes between people during the social rounds; a ring
      means they replied to the brand. Click a dot or a thought to open that person.
    </p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import Ico from './Ico.vue'
import EChart from './EChart.vue'
import { palette } from '../../workspace/charts.js'
import { spread, worldGeo } from '../../workspace/geo.js'
import { feedEdges, plainDid } from '../../workspace/runActivity.js'

const props = defineProps({
  index: { type: Array, default: () => [] },
  story: { type: Object, default: null },
  harvest: { type: Object, default: null },
  theme: { type: String, default: 'dark' },
  live: Boolean,
  big: Boolean,
  height: { type: Number, default: 360 },
  selected: { type: [Number, String], default: null }
})
const emit = defineEmits(['select', 'expand'])
const el = ref(null), step = ref(0), playing = ref(false), scrubbed = ref(false), geo = ref(null)
const layers = reactive({ reply: true, like: true, quote: true })
let chart = null, echartsLib = null, timer = null, observer = null
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

const people = computed(() => props.index.filter((r) => (r.kind || 'persona') === 'persona'))
const byId = computed(() => Object.fromEntries(people.value.map((p) => [String(p.agent_id), p])))
const segments = computed(() => [...new Set(people.value.map((p) => p.segment || 'No segment'))])
const colorOf = (seg) => palette().series[Math.max(0, segments.value.indexOf(seg || 'No segment')) % palette().series.length]
const kinds = computed(() => {
  const p = palette()
  return [{ id: 'reply', label: 'Replies', color: p.series[2] }, { id: 'like', label: 'Likes', color: p.yes }, { id: 'quote', label: 'Quotes and shares', color: '#e0559a' }]
})

const edges = computed(() => feedEdges(props.story))
const roundOf = (t) => {
  const m = String(t.context || '').match(/round (\d+)/i)
  return m ? Number(m[1]) : null
}
const thoughts = computed(() => (props.harvest?.entries || []).filter((t) => t.text).map((t) => {
  const r = t.source === 'social feed' ? roundOf(t) : null
  const phase = r !== null ? 'round' : /survey|pitch/i.test(t.source || '') ? 'after' : 'before'
  return { ...t, round: r, phase }
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
const allById = computed(() => Object.fromEntries(props.index.map((r) => [String(r.agent_id), r])))
const stepThoughts = computed(() => thoughts.value.filter((t) => inStep(t)).slice(0, 40).map((t) => {
  const p = allById.value[String(t.agent_id)] || {}
  const account = p.kind && p.kind !== 'persona' ? (p.kind === 'community' ? 'Community account' : 'Brand account') : ''
  return { agent_id: t.agent_id, account, who: t.name || p.name || `Person ${t.agent_id}`, segment: account || t.segment || p.segment, country: account ? '' : p.country, text: t.text, did: plainDid(t.did),
    kind: t.kind, kindLabel: { private_thought: 'thought', said: 'said', posted: 'posted' }[t.kind] || t.kind, color: colorOf(t.segment || p.segment) }
}))
const activeIds = computed(() => new Set([...stepEdges.value.map((e) => String(e.from)), ...stepThoughts.value.map((t) => String(t.agent_id))]))
const feedTitle = computed(() => ({ before: 'Thinking while scrolling', after: 'What they told us afterwards', all: 'Everything written in the rounds' })[current.value?.id] || 'Written this round')

// positions: each person's country centre, spread so a country's people do not overlap
const positions = computed(() => {
  const g = geo.value
  const out = {}
  if (!g) return out
  const counts = {}
  for (const p of people.value) {
    const c = g.match(p.country)
    if (c) counts[c] = (counts[c] || 0) + 1
  }
  for (const p of people.value) {
    const c = g.match(p.country)
    const centre = c && g.centroid(c)
    if (centre) out[String(p.agent_id)] = spread(centre, p.agent_id, counts[c])
  }
  return out
})
const perRound = computed(() => {
  props.theme // re-colour with the theme
  const p = palette()
  const rs = rounds.value
  const count = (k, r) => edges.value.filter((e) => e.kind === k && e.round === r).length
  const kc = Object.fromEntries(kinds.value.map((k) => [k.id, k.color]))
  return {
    animationDuration: 500, textStyle: { color: p.text, fontFamily: 'inherit' },
    grid: { left: 8, right: 10, top: 28, bottom: 6, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true },
    legend: { top: 0, textStyle: { color: p.muted, fontSize: 11 } },
    xAxis: { type: 'category', data: rs.map((r) => `R${r}`), axisLabel: { color: p.muted }, axisLine: { lineStyle: { color: p.line } } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: p.muted }, splitLine: { lineStyle: { color: p.line } } },
    series: kinds.value.map((k) => ({ name: k.label, type: 'bar', stack: 'all', data: rs.map((r) => count(k.id, r)), itemStyle: { color: kc[k.id] } }))
  }
})
const topPosts = computed(() => {
  const list = []
  for (const [platform, pl] of Object.entries(props.story?.platforms || {})) {
    for (const post of pl.posts || []) {
      const replies = (post.comments || []).length, likes = post.likes || (post.likers || []).length || 0, quotes = (post.quotes || []).length
      const a = post.author || {}
      list.push({ who: a.name || 'Someone', person: a.kind === 'persona', agentId: a.agent_id, text: String(post.content || '').slice(0, 160),
        where: [{ twitter: 'Twitter-style', reddit: 'Reddit-style' }[platform] || platform, post.round !== undefined ? `round ${post.round}` : '', a.kind === 'persona' ? '' : 'brand'].filter(Boolean).join(' · '),
        replies, likes, quotes, score: replies * 3 + quotes * 2 + likes })
    }
  }
  return list.sort((a, b) => b.score - a.score).slice(0, 5)
})
const placed = computed(() => Object.keys(positions.value).length)
const summary = computed(() => `World map: ${placed.value} of ${people.value.length} simulated people placed in their countries. ${current.value?.label || ''}: ${stepEdges.value.length} interactions and ${stepThoughts.value.length} written thoughts.`)

function option() {
  const p = palette()
  const dark = props.theme === 'dark'
  const pos = positions.value
  const kindColor = Object.fromEntries(kinds.value.map((k) => [k.id, k.color]))
  const line = (e) => (pos[String(e.from)] && pos[String(e.to)] ? { coords: [pos[String(e.from)], pos[String(e.to)]], lineStyle: { color: kindColor[e.kind] } } : null)
  // one small ring per person who answered the brand this round (left out of the all-rounds view, where it would cover the dots)
  const seen = new Set()
  const brandPulses = current.value?.id === 'all' ? [] : stepEdges.value.filter((e) => e.toBrand && pos[String(e.from)] && !seen.has(e.from) && seen.add(e.from))
    .map((e) => ({ value: pos[String(e.from)], itemStyle: { color: kindColor[e.kind] } }))
  const active = activeIds.value
  const peopleData = people.value.filter((x) => pos[String(x.agent_id)]).map((x) => {
    const id = String(x.agent_id)
    const on = !current.value || active.has(id)
    const sel = String(props.selected) === id
    return {
      id, name: x.name || `Person ${id}`, value: pos[id], segment: x.segment, country: x.country,
      symbolSize: sel ? 14 : on ? 9 : 5,
      itemStyle: { color: colorOf(x.segment), opacity: on || sel ? 1 : 0.35, borderColor: sel ? p.text : 'transparent', borderWidth: sel ? 2 : 0 }
    }
  })
  return {
    animationDurationUpdate: 400,
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item', confine: true,
      formatter: (x) => (x.seriesId === 'people' ? `<b>${x.data.name}</b><br>${[x.data.segment, x.data.country].filter(Boolean).join(' · ')}<br><i>Click to open</i>` : x.seriesType === 'map' || x.componentType === 'geo' ? x.name : '')
    },
    geo: {
      map: 'mm-world', roam: true, ...frame(), scaleLimit: { min: 0.8, max: 14 },
      itemStyle: { areaColor: dark ? '#1f2a33' : '#e6ece8', borderColor: dark ? '#33424d' : '#c3cfc8', borderWidth: 0.6 },
      emphasis: { itemStyle: { areaColor: dark ? '#2b3a45' : '#d6e2db' }, label: { show: false } },
      select: { disabled: true }, label: { show: false }
    },
    series: [
      { id: 'past', type: 'lines', coordinateSystem: 'geo', silent: true, zlevel: 1, polyline: false,
        lineStyle: { width: 0.8, opacity: 0.18, curveness: 0.25 }, data: pastEdges.value.map(line).filter(Boolean) },
      { id: 'now', type: 'lines', coordinateSystem: 'geo', silent: true, zlevel: 2,
        effect: { show: !reduced, period: 2.2, trailLength: 0.35, symbol: 'arrow', symbolSize: 6 },
        lineStyle: { width: 1.6, opacity: 0.75, curveness: 0.25 }, data: stepEdges.value.map(line).filter(Boolean) },
      { id: 'brand', type: 'effectScatter', coordinateSystem: 'geo', silent: true, zlevel: 2, symbolSize: 7,
        rippleEffect: { scale: reduced ? 1 : 2.4, brushType: 'stroke', number: 2 }, itemStyle: { opacity: 0.8 }, data: brandPulses },
      { id: 'people', type: 'scatter', coordinateSystem: 'geo', zlevel: 3, data: peopleData, cursor: 'pointer', emphasis: { scale: 1.6 } }
    ]
  }
}
let framed = null
function frame() {
  // fit the view to where the people are (with room around them); after that, keep the user's pan and zoom
  if (framed) return {}
  const pts = Object.values(positions.value)
  if (!pts.length) return {}
  const lons = pts.map((x) => x[0]), lats = pts.map((x) => x[1])
  const pad = 14
  framed = { boundingCoords: [[Math.max(-180, Math.min(...lons) - pad), Math.min(85, Math.max(...lats) + pad)], [Math.min(180, Math.max(...lons) + pad), Math.max(-60, Math.min(...lats) - pad)]] }
  return framed
}

async function render() {
  if (!el.value || !geo.value) return
  if (!echartsLib) {
    echartsLib = await import('echarts')
    if (!echartsLib.getMap('mm-world')) echartsLib.registerMap('mm-world', geo.value.geojson)
  }
  if (!chart) {
    chart = echartsLib.init(el.value, null, { renderer: 'canvas' })
    chart.on('click', (x) => x.seriesId === 'people' && emit('select', Number.isNaN(Number(x.data.id)) ? x.data.id : Number(x.data.id)))
  }
  chart.setOption(option(), { replaceMerge: ['series'] })
}

function toggle() {
  playing.value = !playing.value
  if (playing.value && step.value >= steps.value.length - 1) step.value = 0
}
watch(playing, (v) => {
  clearInterval(timer)
  if (v) timer = setInterval(() => {
    if (step.value >= steps.value.length - 1) playing.value = false
    else step.value++
  }, reduced ? 3500 : 2400)
})
// a live run follows the newest step unless you moved the slider
watch(() => steps.value.length, (n, old) => {
  if (props.live && !scrubbed.value) step.value = Math.max(0, n - 1 - (steps.value[n - 1]?.id === 'all' ? 1 : 0))
  else if (!old && n) step.value = n - 1 // open on everything; press play to watch it round by round
}, { immediate: true })
watch(() => [step.value, props.theme, props.selected, positions.value, layers.reply, layers.like, layers.quote, props.story, props.harvest], render)

onMounted(async () => {
  geo.value = await worldGeo()
  await render()
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(el.value)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  observer && observer.disconnect()
  chart && chart.dispose()
})
</script>
