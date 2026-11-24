<template>
  <section class="agent-card" :aria-label="`Results of ${artifact.run}`">
    <header><ChartNoAxesCombined :size="16" aria-hidden="true" /><b>{{ artifact.run }}</b><SimulatedBadge /></header>
    <p v-if="decision" class="agent-decision"><span :class="decisionTone(decision.decision)">{{ decisionText(decision.decision) }}</span> {{ decision.summary }}</p>
    <dl v-if="overall" class="agent-spend">
      <div><dt>Would buy</dt><dd>{{ pct(overall.convert_yes) }}</dd></div>
      <div><dt>Maybe</dt><dd>{{ pct(overall.convert_maybe) }}</dd></div>
      <div><dt>Answered</dt><dd>{{ overall.n ?? '—' }}</dd></div>
    </dl>
    <table v-if="artifact.by_segment?.length" class="agent-steps">
      <caption>Would buy by audience</caption>
      <tr v-for="s in artifact.by_segment" :key="s.key"><th scope="row">{{ s.key }} <small>(n={{ s.n }})</small></th><td>{{ pct(s.convert_yes) }}</td></tr>
    </table>
    <p v-if="artifact.objections?.length" class="agent-note">Top objections: {{ artifact.objections.map((o) => `${o.label} (${o.share}%)`).join(', ') }}</p>
    <div class="agent-actions"><button type="button" @click="emit('open', artifact.run)">Open the reports</button></div>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { ChartNoAxesCombined } from 'lucide-vue-next'
import SimulatedBadge from './SimulatedBadge.vue'
import { decisionText, decisionTone } from '../../../workspace/compareRuns.js'
const props = defineProps({ artifact: { type: Object, required: true } })
const emit = defineEmits(['open'])
const decision = computed(() => (props.artifact.decision && typeof props.artifact.decision === 'object' ? props.artifact.decision : props.artifact.decision ? { decision: props.artifact.decision } : null))
const overall = computed(() => props.artifact.overall || null)
const pct = (v) => (typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v * 10) / 10}%` : '—')
</script>
<style scoped src="./agent-cards.css"></style>
<style scoped>
.agent-decision { font-size: 13px; }
.agent-decision span { display: inline-block; padding: 1px 8px; margin-right: 6px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--panel-2); }
</style>
