<template>
  <section class="ra" aria-label="What happened during the run">
    <div v-if="byRound.rounds.length" class="ra-card">
      <h3>What people did in each social round <small>simulated</small></h3>
      <EChart :option="roundChart" :height="240" :theme="theme" label="Actions in each social round by kind: posted, commented, liked, shared and only read" />
      <p class="ra-note">"Only read" means the person scrolled that round without posting, replying or liking.</p>
    </div>

    <div v-if="analysts.length" class="ra-card">
      <h3>What the analyst panel concluded <small>{{ analysts.length }} simulated analysts, each with a different lens</small></h3>
      <div v-if="consensusLine" class="ra-consensus"><Users :size="15" aria-hidden="true" />{{ consensusLine }}</div>
      <div class="ra-analysts">
        <article v-for="a in analysts" :key="a.id" class="ra-analyst">
          <header>
            <b>{{ a.lens }}</b>
            <span v-if="a.verdict" :class="['ra-pill', tone(a.verdict)]">{{ cap(a.verdict) }}</span>
            <span v-if="a.confidence !== null" class="ra-conf" :title="`Confidence ${a.confidence} out of 10`">{{ a.confidence }}/10 sure</span>
          </header>
          <p v-if="a.error" class="ra-err">This analyst failed: {{ a.error }}</p>
          <template v-else>
            <p class="ra-headline">{{ a.headline || a.recommendation || 'No summary saved.' }}</p>
            <dl>
              <template v-if="a.bestAudience"><dt>Best audience</dt><dd>{{ a.bestAudience }}</dd></template>
              <template v-if="a.bestMessage"><dt>Best message</dt><dd>{{ a.bestMessage }}</dd></template>
            </dl>
            <details v-if="a.objections.length || a.gaps">
              <summary>Objections and what is missing</summary>
              <ul v-if="a.objections.length"><li v-for="(o, i) in a.objections.slice(0, 4)" :key="i">{{ o }}</li></ul>
              <p v-if="a.gaps" class="ra-gaps"><b>Needs real data on:</b> {{ a.gaps }}</p>
            </details>
          </template>
        </article>
      </div>
    </div>

    <div v-if="topPeople.length" class="ra-card">
      <h3>Most active people <small>{{ agents.length.toLocaleString() }} people took part</small></h3>
      <ol class="ra-people">
        <li v-for="p in topPeople" :key="p.id">
          <span class="ra-name">{{ p.name }}</span>
          <span class="ra-stack" role="img" :aria-label="p.aria">
            <i v-for="s in p.parts" :key="s.kind" :style="{ width: s.pct + '%', background: kindColor[s.kind] }"></i>
          </span>
          <span class="ra-n">{{ p.total }}</span>
        </li>
      </ol>
      <ul class="ra-key">
        <li v-for="k in shownKinds" :key="k"><i :style="{ background: kindColor[k] }" aria-hidden="true"></i>{{ cap(k) }}</li>
      </ul>
    </div>

    <p v-if="!byRound.rounds.length && !analysts.length && !agents.length" class="ws-empty">No activity was saved in this run.</p>
  </section>
</template>

<script setup>
// The Activity tab: actions per social round by kind, the analyst panel's full readouts, and the most active people.
import { computed } from 'vue'
import { Users } from 'lucide-vue-next'
import EChart from './EChart.vue'
import { actionsByRound } from '../../workspace/responses'

const props = defineProps({ timeline: { type: Array, default: () => [] }, panel: { type: Object, default: null }, agents: { type: Array, default: () => [] }, theme: { type: String, default: 'light' } })

const kindColor = { posted: '#507cba', commented: '#278d99', liked: '#2f8f5b', disliked: '#c2554d', shared: '#d0558f', followed: '#9568aa', 'only read': '#b8bec6' }
const cap = (s) => { s = String(s || '').replace(/_/g, ' '); return s ? s[0].toUpperCase() + s.slice(1) : '' }
const tone = (v) => (/no.?go|stop|kill/i.test(v) ? 'no' : /^go$|launch|scale/i.test(v) ? 'yes' : 'maybe')

const byRound = computed(() => actionsByRound(props.timeline))
const roundChart = computed(() => {
  const dark = props.theme === 'dark', muted = dark ? '#b0b3b8' : '#686e73', line = dark ? '#303237' : '#e8ebe9'
  const r = byRound.value
  return {
    textStyle: { fontFamily: 'inherit', color: dark ? '#ececec' : '#17181a' },
    grid: { left: 4, right: 10, top: 34, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, confine: true },
    legend: { top: 0, textStyle: { color: muted, fontSize: 11 }, itemWidth: 10, itemHeight: 10 },
    xAxis: { type: 'category', data: r.rounds.map((n) => `Round ${n}`), axisLabel: { color: muted }, axisLine: { lineStyle: { color: line } } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
    series: Object.entries(r.series).map(([k, data]) => ({ name: cap(k), type: 'bar', stack: 'all', data, itemStyle: { color: kindColor[k] }, emphasis: { focus: 'series' } }))
  }
})

const analysts = computed(() => (props.panel?.analysts || []).map((a, i) => {
  const r = a.result || {}
  const conf = Number(r.confidence)
  return {
    id: a.id || `a${i}`, lens: a.lens || a.id || `Analyst ${i + 1}`, error: a.error || '', verdict: r.verdict || '',
    confidence: Number.isFinite(conf) ? Math.round(conf) : null, headline: r.headline || '', recommendation: r.recommendation || '',
    bestAudience: typeof r.best_audience === 'string' ? r.best_audience : '', bestMessage: typeof r.best_message === 'string' ? r.best_message : '',
    objections: Array.isArray(r.objections) ? r.objections.map(String) : [], gaps: typeof r.evidence_gaps === 'string' ? r.evidence_gaps : ''
  }
}))
const consensusLine = computed(() => {
  const c = props.panel?.consensus || {}
  const verdict = c.verdict?.winner || c.decision?.winner
  const agree = c.verdict?.agreement ?? c.decision?.agreement
  const audience = c.best_audience?.winner
  const parts = []
  if (verdict) parts.push(`Most analysts say ${cap(verdict).toLowerCase()}${Number.isFinite(+agree) ? ` (${agree}% agree)` : ''}.`)
  if (audience) parts.push(`Top audience pick: ${audience}.`)
  return parts.join(' ')
})

const kindOf = { CREATE_POST: 'posted', CREATE_COMMENT: 'commented', LIKE_POST: 'liked', LIKE_COMMENT: 'liked', DISLIKE_POST: 'disliked', DISLIKE_COMMENT: 'disliked', REPOST: 'shared', QUOTE_POST: 'shared', FOLLOW: 'followed' }
const topPeople = computed(() => props.agents.map((a) => {
  const parts = {}
  for (const [t, n] of Object.entries(a.action_types || {})) { const k = kindOf[String(t).toUpperCase()]; if (k && n) parts[k] = (parts[k] || 0) + n }
  const total = Object.values(parts).reduce((x, y) => x + y, 0)
  return { id: a.agent_id, name: a.agent_name || `Person ${a.agent_id}`, total, parts: Object.entries(parts).map(([kind, n]) => ({ kind, n, pct: total ? (100 * n) / total : 0 })),
    aria: Object.entries(parts).map(([k, n]) => `${n} ${k}`).join(', ') }
}).filter((p) => p.total).sort((a, b) => b.total - a.total).slice(0, 12))
const shownKinds = computed(() => [...new Set(topPeople.value.flatMap((p) => p.parts.map((s) => s.kind)))])
</script>

<style scoped>
.ra { display: grid; gap: 14px; min-width: 0; }
.ra-card { border: 1px solid var(--line); border-radius: 12px; background: var(--panel); padding: 14px 16px; min-width: 0; }
.ra-card h3 { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; margin: 0 0 10px; font-size: 14px; }
.ra-card h3 small { font-weight: 400; font-size: 12px; color: var(--muted); }
.ra-note { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
.ra-consensus { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; border-radius: 10px; background: var(--panel-2); font-size: 13px; margin-bottom: 12px; }
.ra-analysts { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
.ra-analyst { border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; display: grid; gap: 8px; align-content: start; }
.ra-analyst header { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; font-size: 13px; }
.ra-pill { font-size: 11px; font-weight: 600; padding: 1px 8px; border-radius: 999px; border: 1px solid currentColor; }
.ra-pill.yes { color: #2f8f5b; } .ra-pill.maybe { color: #a87a1c; } .ra-pill.no { color: #c2554d; }
.ra-conf { margin-left: auto; font-size: 11.5px; color: var(--muted); }
.ra-headline { margin: 0; font-size: 13px; line-height: 1.5; }
.ra-analyst dl { margin: 0; display: grid; gap: 4px; font-size: 12.5px; }
.ra-analyst dt { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
.ra-analyst dd { margin: 0 0 4px; line-height: 1.45; }
.ra-analyst details { font-size: 12.5px; }
.ra-analyst summary { cursor: pointer; color: var(--accent); font-weight: 600; }
.ra-analyst ul { margin: 6px 0; padding-left: 18px; line-height: 1.45; }
.ra-gaps { margin: 4px 0 0; color: var(--muted); line-height: 1.45; }
.ra-gaps b { color: var(--text); }
.ra-err { margin: 0; color: #c2554d; font-size: 12.5px; }
.ra-people { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.ra-people li { display: grid; grid-template-columns: minmax(90px, 200px) minmax(0, 1fr) 36px; gap: 10px; align-items: center; font-size: 12.5px; }
.ra-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ra-stack { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--line); }
.ra-stack i { display: block; height: 100%; }
.ra-n { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
.ra-key { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 11.5px; color: var(--muted); }
.ra-key li { display: inline-flex; align-items: center; gap: 5px; }
.ra-key i { width: 9px; height: 9px; border-radius: 3px; }
.ra summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 600px) { .ra-people li { grid-template-columns: 100px minmax(0, 1fr) 30px; } .ra-card { padding: 12px; } }
</style>
