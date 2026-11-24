<template>
  <div class="agent-turn">
    <template v-for="(c, i) in turn.cards" :key="i">
      <p v-if="c.type === 'note'" class="agent-turn-note">{{ c.text }}</p>
      <ToolCard v-else-if="c.type === 'tool'" :card="c" />
      <template v-else-if="c.type === 'approval'">
        <MissingInputsCard v-if="c.card.kind === 'form'" :card="c.card" :answered="answeredLabel(c)" :busy="busy" @answer="answer" />
        <AudienceDesignCard v-else-if="c.card.kind === 'audience'" :card="c.card" :answered="answeredLabel(c)" :busy="busy" @answer="answer" />
        <ApprovalCard v-else :card="c.card" :answered="answeredLabel(c)" :busy="busy" @answer="answer" />
      </template>
      <template v-else-if="c.type === 'artifact'">
        <AgentViewCard v-if="c.kind === 'view'" :artifact="c" :runs="runs" :theme="theme" @action="(a) => emit('run-action', a)" @loaded="(d) => emit('run-loaded', d)" />
        <ResultsCard v-else-if="c.kind === 'results'" :artifact="c" @open="(run) => emit('open-run', run)" />
      </template>
    </template>
    <LoadingSkeleton v-if="turn.status === 'working' && !turn.cards.length" class="agent-turn-skeleton" :lines="2" label="Working on your answer" />
    <div v-if="turn.error" class="agent-card agent-turn-error" role="alert">
      <p><CircleAlert :size="15" aria-hidden="true" />{{ turn.error.message }}</p>
      <div v-if="turn.error.actions?.length" class="agent-actions">
        <button v-for="(a, i) in turn.error.actions" :key="a.id" type="button" :class="{ primary: i === 0 }" @click="emit('action', a.id)">{{ a.label }}</button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { CircleAlert } from 'lucide-vue-next'
import ToolCard from './ToolCard.vue'
import ApprovalCard from './ApprovalCard.vue'
import MissingInputsCard from './MissingInputsCard.vue'
import AudienceDesignCard from './AudienceDesignCard.vue'
import ResultsCard from './ResultsCard.vue'
import AgentViewCard from './AgentViewCard.vue'
import LoadingSkeleton from '../LoadingSkeleton.vue'
const props = defineProps({ turn: { type: Object, required: true }, runs: { type: Array, default: () => [] }, theme: { type: String, default: 'light' }, busy: Boolean })
const emit = defineEmits(['resume', 'action', 'open-run', 'run-action', 'run-loaded'])
// a card can be answered only while it is the turn's open approval; older ones show what was chosen (or that they lapsed)
function answeredLabel(c) {
  if (c.answered) return c.answered
  return props.turn.pending?.id === c.card.id ? null : 'No longer open'
}
function answer(payload) { emit('resume', payload) }
</script>
<style scoped src="./agent-cards.css"></style>
<style scoped>
.agent-turn { margin-top: 6px; }
.agent-turn-note { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); margin: 6px 0; }
.agent-turn-error p { display: flex; gap: 8px; align-items: flex-start; }
.agent-turn-error svg { color: #c2410c; flex-shrink: 0; margin-top: 3px; }
.agent-turn-skeleton { max-width: 420px; }
</style>
