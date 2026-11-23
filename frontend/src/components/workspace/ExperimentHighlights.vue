<script setup>
import { computed, ref } from 'vue'
import { readableLabel } from '../../workspace/reportPresentation'

const props = defineProps({ summary: { type: Object, required: true }, canOpenFeed: Boolean })
const emit = defineEmits(['open-feed'])
const marketing = computed(() => props.summary.marketing || {})
const outcome = computed(() => props.summary.decision || {})
const overall = computed(() => marketing.value.overall || {})
const audience = ref('by_segment')
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
const format = value => number.format(value)
const percent = value => `${format(value)}%`
const numeric = value => Number.isFinite(value) && value >= 0
const label = value => value === 'no-go' ? 'Do not proceed' : value === 'go' ? 'Proceed' : value === 'iterate' ? 'Revise and retest' : readableLabel(value)
const actionLabels = {
  LIKE_COMMENT: 'Comment likes', CREATE_COMMENT: 'Comments', DO_NOTHING: 'No action',
  LIKE_POST: 'Post likes', DISLIKE_POST: 'Post dislikes', CREATE_POST: 'Posts', SEARCH_POSTS: 'Searches',
}
const groups = computed(() => [
  ['by_segment', 'Segments'], ['by_country', 'Countries'], ['by_community', 'Communities']
].filter(([key]) => marketing.value[key]?.length))
const activeAudience = computed(() => groups.value.some(([key]) => key === audience.value) ? audience.value : groups.value[0]?.[0])
const comparisons = computed(() => {
  const rows = (marketing.value[activeAudience.value] || []).filter(row => typeof row.key === 'string')
  return [...rows].sort((a, b) => (b.convert_yes ?? -1) - (a.convert_yes ?? -1))
})
const trialRecorded = computed(() => comparisons.value.some(row => numeric(row.convert_yes)))
const maxPeople = computed(() => Math.max(1, ...comparisons.value.map(row => numeric(row.n) ? row.n : 0)))
const measuredGroups = computed(() => comparisons.value.filter(row => numeric(row.convert_yes)))
const highest = computed(() => measuredGroups.value[0])
const lowest = computed(() => measuredGroups.value.at(-1))
const conversionMax = computed(() => Math.max(1, highest.value?.convert_yes ?? 0))
const funnel = computed(() => (marketing.value.funnel || []).filter(row => Array.isArray(row) && typeof row[0] === 'string' && numeric(row[1])))
const funnelMax = computed(() => Math.max(1, ...funnel.value.map(([, value]) => value)))
const surveyed = computed(() => numeric(marketing.value.answered) ? marketing.value.answered : overall.value.n)
const objections = computed(() => (marketing.value.objections || []).filter(row => typeof row.label === 'string' && numeric(row.count)))
const actions = computed(() => Object.entries(props.summary.action_types || {})
  .filter(([, value]) => numeric(value))
  .sort((a, b) => b[1] - a[1]))
const actionMax = computed(() => Math.max(1, ...actions.value.map(([, value]) => value)))
const messages = computed(() => (marketing.value.messages_ranked || []).filter(row => typeof row.label === 'string'))
const metrics = computed(() => [
  ['Survey respondents', surveyed.value],
  ['Agents generated', props.summary.agents],
  ['Recorded actions', props.summary.total_actions],
  ['Relationship edges', props.summary.graph?.edge_count],
].filter(([, value]) => numeric(value)))
const scores = computed(() => [
  ['Interest', overall.value.interest, overall.value.ssr?.interest?.mean],
  ['Trust', overall.value.trust, overall.value.ssr?.trust?.mean],
  ['Purchase intent', null, overall.value.ssr?.purchase?.mean]
].filter(([, stated, semantic]) => numeric(stated) || numeric(semantic)))
const bar = (value, maximum) => ({ width: `${Math.min(100, value / maximum * 100)}%` })
</script>

<template>
  <section class="experiment-highlights" aria-label="Experiment highlights">
    <header v-if="outcome.decision || marketing.offer" class="experiment-decision">
      <h3>{{ outcome.decision ? label(outcome.decision) : 'Offer tested' }}</h3>
      <p v-if="outcome.summary">{{ outcome.summary }}</p>
      <p v-if="marketing.offer" class="experiment-offer"><strong>Offer tested</strong> {{ marketing.offer }}</p>
    </header>

    <dl v-if="metrics.length" class="experiment-metrics">
      <div v-for="[name, value] in metrics" :key="name"><dt>{{ name }}</dt><dd>{{ format(value) }}</dd></div>
    </dl>

    <div class="experiment-grid">
      <section v-if="funnel.length" class="experiment-panel">
        <h4>Survey funnel</h4>
        <p>Counts from simulated responses.</p>
        <ol class="experiment-bars">
          <li v-for="[name, count] in funnel" :key="name">
            <div><span>{{ name }}</span><strong>{{ format(count) }}</strong></div>
            <div class="experiment-track" aria-hidden="true"><span :style="bar(count, funnelMax)"></span></div>
          </li>
        </ol>
        <div v-if="numeric(overall.click_yes) || numeric(overall.convert_yes)" class="experiment-inline-stats">
          <p v-if="numeric(overall.click_yes)"><strong>{{ percent(overall.click_yes) }}</strong> definite click<template v-if="numeric(overall.click_maybe)"> · {{ percent(overall.click_maybe) }} maybe</template></p>
          <p v-if="numeric(overall.convert_yes)"><strong>{{ percent(overall.convert_yes) }}</strong> definite conversion<template v-if="numeric(overall.convert_maybe)"> · {{ percent(overall.convert_maybe) }} maybe</template></p>
        </div>
      </section>

      <section v-if="objections.length" class="experiment-panel">
        <h4>Top objections</h4>
        <p>Share of simulated survey responses where recorded.</p>
        <ol class="experiment-bars objections">
          <li v-for="row in objections" :key="row.label">
            <div><span>{{ row.label }}</span><strong>{{ numeric(row.share) ? percent(row.share) : format(row.count) }}</strong></div>
            <div v-if="numeric(row.share)" class="experiment-track" aria-hidden="true"><span :style="bar(row.share, 100)"></span></div>
            <small>{{ format(row.count) }} responses</small>
          </li>
        </ol>
      </section>

      <section v-if="comparisons.length" class="experiment-panel">
        <div class="experiment-panel-heading">
          <h4>Compare audiences</h4>
          <select :value="activeAudience" aria-label="Audience breakdown" @change="audience = $event.target.value">
            <option v-for="[id, name] in groups" :key="id" :value="id">{{ name }}</option>
          </select>
        </div>
        <p>{{ trialRecorded ? 'Definite conversion rate among surveyed personas.' : 'Count of surveyed personas by group.' }}</p>
        <p v-if="activeAudience === 'by_community'">Community membership can overlap.</p>
        <dl v-if="highest && lowest && highest.convert_yes > lowest.convert_yes" class="experiment-ends">
          <div><dt>Highest recorded</dt><dd>{{ highest.key }} <strong>{{ percent(highest.convert_yes) }}</strong></dd></div>
          <div><dt>Lowest recorded</dt><dd>{{ lowest.key }} <strong>{{ percent(lowest.convert_yes) }}</strong></dd></div>
        </dl>
        <ol class="experiment-bars">
          <li v-for="row in comparisons" :key="row.key">
            <div><span>{{ row.key }}</span><strong>{{ trialRecorded && numeric(row.convert_yes) ? percent(row.convert_yes) : numeric(row.n) && !trialRecorded ? format(row.n) : '—' }}</strong></div>
            <div v-if="trialRecorded && numeric(row.convert_yes) || !trialRecorded && numeric(row.n)" class="experiment-track" aria-hidden="true">
              <span :style="trialRecorded ? bar(row.convert_yes, conversionMax) : bar(row.n, maxPeople)"></span>
            </div>
            <small v-if="numeric(row.n)">{{ format(row.n) }} responses<template v-if="numeric(row.click_yes)"> · {{ percent(row.click_yes) }} definite click</template></small>
          </li>
        </ol>
      </section>

      <section v-if="messages.length" class="experiment-panel">
        <h4>Messages tested</h4>
        <p>Saved message variants and their survey responses.</p>
        <ol class="experiment-bars experiment-messages">
          <li v-for="row in messages" :key="row.key">
            <div><span>{{ row.label }}</span></div>
            <small>
              <template v-if="numeric(row.click_yes)">{{ percent(row.click_yes) }} definite click</template>
              <template v-if="numeric(row.click_yes) && numeric(row.convert_yes)"> · </template>
              <template v-if="numeric(row.convert_yes)">{{ percent(row.convert_yes) }} definite conversion</template>
            </small>
          </li>
        </ol>
      </section>

      <section v-if="scores.length" class="experiment-panel">
        <h4>Survey ratings</h4>
        <p>Stated ratings and scores inferred from written responses.</p>
        <div class="experiment-score" v-for="[name, stated, semantic] in scores" :key="name">
          <strong>{{ name }}</strong>
          <div v-if="numeric(stated)"><span>Stated</span><meter min="0" max="5" :value="stated" :aria-label="`${name}, stated`"></meter><b>{{ format(stated) }}/5</b></div>
          <div v-if="numeric(semantic)"><span>Semantic</span><meter min="0" max="5" :value="semantic" :aria-label="`${name}, semantic`"></meter><b>{{ format(semantic) }}/5</b></div>
        </div>
      </section>

      <section v-if="actions.length" class="experiment-panel">
        <div class="experiment-panel-heading">
          <h4>Social activity</h4>
          <button v-if="canOpenFeed" type="button" class="ws-btn" @click="emit('open-feed')">Open feed</button>
        </div>
        <p v-if="numeric(summary.total_rounds)">{{ format(summary.total_rounds) }} configured rounds<template v-if="numeric(summary.graph?.node_count)"> · {{ format(summary.graph.node_count) }} relationship nodes</template></p>
        <ol class="experiment-bars social">
          <li v-for="[name, count] in actions" :key="name">
            <div><span>{{ actionLabels[name] || readableLabel(name.toLowerCase()) }}</span><strong>{{ format(count) }}</strong></div>
            <div class="experiment-track" aria-hidden="true"><span :style="bar(count, actionMax)"></span></div>
          </li>
        </ol>
      </section>
    </div>

    <p v-if="!metrics.length && !funnel.length && !objections.length && !comparisons.length && !scores.length && !actions.length">This run has no saved highlight metrics. Open the reports to inspect its available evidence.</p>
    <p class="experiment-source">Source: saved experiment summary. Simulation responses represent stated intent.</p>
  </section>
</template>

<style scoped>
.experiment-highlights { padding: 14px; display: grid; gap: 12px; }
.experiment-decision { padding: 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-2); }
.experiment-decision h3 { font-size: 18px; font-weight: 650; margin: 0 0 5px; }
.experiment-decision p { font-size: 13px; line-height: 1.55; margin: 5px 0 0; }
.experiment-offer { color: var(--muted); }
.experiment-offer strong { color: var(--text); margin-right: 6px; }
.experiment-metrics, .experiment-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 0; }
.experiment-metrics > div, .experiment-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px; min-width: 0; }
.experiment-metrics dt, .experiment-panel p, .experiment-source { color: var(--muted); font-size: 12px; line-height: 1.55; }
.experiment-metrics dd { margin: 4px 0 0; font-size: 22px; font-weight: 650; }
.experiment-metrics dd, .experiment-bars strong, .experiment-score b { font-variant-numeric: tabular-nums; }
.experiment-panel h4 { font-size: 14px; margin: 0; font-weight: 650; }
.experiment-panel p { margin: 5px 0 0; }
.experiment-panel-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 5px; }
.experiment-panel-heading select { padding: 4px 7px; border: 1px solid var(--line); border-radius: 7px; color: var(--text); background: var(--panel); font-size: 12px; }
.experiment-bars { display: grid; gap: 7px; list-style: none; margin: 10px 0 0; padding: 0; max-height: 260px; overflow: auto; }
.experiment-bars li > div:first-child { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; font-size: 12px; }
.experiment-bars li span { overflow-wrap: anywhere; }
.experiment-bars strong { white-space: nowrap; }
.experiment-bars small { display: block; color: var(--muted); font-size: 11px; }
.experiment-track { margin: 4px 0; height: 5px; border-radius: 5px; background: var(--panel-2); overflow: hidden; }
.experiment-track span { display: block; height: 100%; background: var(--accent); border-radius: inherit; }
.objections .experiment-track span { background: var(--no); }
.social .experiment-track span { background: var(--accent); }
.experiment-inline-stats { margin-top: 10px; padding-top: 5px; border-top: 1px solid var(--line); }
.experiment-score { margin-top: 10px; font-size: 12px; }
.experiment-score > div { display: grid; align-items: center; grid-template-columns: 62px minmax(0,1fr) auto; gap: 6px; margin-top: 4px; }
.experiment-score meter { width: 100%; accent-color: var(--accent); }
.experiment-ends { display: grid; gap: 5px; margin: 9px 0 0; font-size: 11px; }
.experiment-ends > div { padding: 6px 8px; border-radius: 6px; background: var(--panel-2); }
.experiment-ends dt { color: var(--muted); }
.experiment-ends dd { margin: 2px 0 0; }
.experiment-messages li + li { border-top: 1px solid var(--line); padding-top: 7px; }
.experiment-source { margin: 0; }
@media(max-width: 620px) { .experiment-grid { grid-template-columns: 1fr; } }
</style>
