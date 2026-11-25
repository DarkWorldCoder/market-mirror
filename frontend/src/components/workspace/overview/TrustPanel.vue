<template>
  <section class="ovi-panel" aria-labelledby="ovi-trust-heading">
    <div class="ovi-head"><div><h2 id="ovi-trust-heading"><ShieldCheck :size="16" aria-hidden="true" />How much to trust these results</h2><p>Each run gets a grade from A to D based on what it recorded: how many people answered, repeat runs, and checks against real answers.</p></div></div>
    <p v-if="!trust.graded && !trust.calibrated && !forecasts.locked" class="ovi-empty">No run has results to grade yet.</p>
    <template v-else>
      <ul v-if="trust.graded" class="ovi-grades" aria-label="Runs per evidence grade">
        <li v-for="g in grades" :key="g.grade" :class="{ none: !g.count }"><strong>{{ g.grade }}</strong><span>{{ g.count }} {{ plural(g.count, { one: 'run', other: 'runs' }) }}</span><small>{{ gradeText(g.grade) }}</small></li>
      </ul>
      <p class="ovi-real"><b>{{ trust.calibrated }} of {{ totalRuns }}</b> {{ plural(totalRuns, { one: 'run was', other: 'runs were' }) }} checked with real people.</p>
      <p v-if="nudge" class="ovi-nudge"><Info :size="15" aria-hidden="true" />{{ nudge }}</p>
      <ul v-if="recent.length" class="ovi-trust-runs" aria-label="Evidence grade per run">
        <li v-for="row in recent" :key="row.run">
          <span class="ovi-grade" :class="`g${row.grade || 'none'}`" :aria-label="row.grade ? `Grade ${row.grade}` : 'Not graded'">{{ row.grade || '–' }}</span>
          <RouterLink :to="`/workspace/runs/${encodeURIComponent(row.run)}`">{{ row.title || row.run }}</RouterLink>
          <span v-if="row.calibrated" class="ovi-tag ok">Checked with {{ row.n_real ? `${row.n_real} real answers` : 'real answers' }}</span>
          <details v-if="row.reasons?.length" class="ovi-trust-why">
            <summary>Why grade {{ row.grade || '–' }}</summary>
            <ul><li v-for="reason in row.reasons" :key="reason">{{ reason }}</li></ul>
          </details>
        </li>
      </ul>
      <div class="ovi-ledger">
        <h3>Locked forecasts</h3>
        <p v-if="!forecasts.locked" class="ovi-note">No forecasts locked yet. Locking one before real results arrive lets you keep an honest score, misses included.</p>
        <template v-else>
          <p class="ovi-note">{{ forecasts.locked }} locked · {{ forecasts.scored }} scored<template v-if="forecasts.checks"> · {{ forecasts.hits }} of {{ forecasts.checks }} checks hit</template></p>
          <ul class="ovi-ledger-list" aria-label="Locked forecasts, newest first">
            <li v-for="e in forecasts.entries.slice(0, 6)" :key="e.id" :class="e.outcome">
              <component :is="icon(e.outcome)" :size="15" aria-hidden="true" />
              <span><strong>{{ e.run }}</strong><small>{{ summary(e) }}</small></span>
              <span class="ovi-ledger-outcome">{{ outcomeText(e.outcome) }}<template v-if="e.scored && e.total"> ({{ e.hits }}/{{ e.total }})</template></span>
            </li>
          </ul>
        </template>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { CircleCheck, CircleDashed, CircleX, Clock, Info, ShieldCheck } from 'lucide-vue-next'
import { gradeCounts, gradeText, outcomeText, trustNudge } from '../../../workspace/overviewInsights.js'
import { plural } from '../../../workspace/plural.js'

const props = defineProps({ trust: { type: Object, required: true }, forecasts: { type: Object, required: true }, totalRuns: { type: Number, default: 0 } })
const grades = computed(() => gradeCounts(props.trust.grades))
const nudge = computed(() => trustNudge(props.trust, props.totalRuns))
const recent = computed(() => props.trust.runs.slice(0, 6))
const icon = (o) => (o === 'hit' ? CircleCheck : o === 'miss' ? CircleX : o === 'pending' ? Clock : CircleDashed)
function summary(e) {
  const p = e.predicted || {}
  const parts = [p.rate != null ? `predicted ${p.rate}% yes` : '', p.top_segment ? `best group: ${p.top_segment}` : '', p.decision ? `decision: ${String(p.decision).replaceAll('_', ' ')}` : '']
  const when = e.outcome === 'pending' && e.outcome_due ? `due ${e.outcome_due}` : e.locked_at ? `locked ${String(e.locked_at).slice(0, 10)}` : ''
  return [parts.filter(Boolean).join(', '), when].filter(Boolean).join(' · ')
}
</script>
