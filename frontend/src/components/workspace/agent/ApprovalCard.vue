<template>
  <section class="agent-card agent-approval" :class="card.kind" :aria-label="card.title || 'Approval'">
    <header>
      <Wallet v-if="card.kind === 'spend'" :size="16" aria-hidden="true" />
      <Globe v-else-if="card.kind === 'outside'" :size="16" aria-hidden="true" />
      <Gauge v-else :size="16" aria-hidden="true" />
      <b>{{ card.title || 'Before I go on' }}</b>
      <span v-if="answered" class="agent-answered">{{ answered }}</span>
    </header>
    <p class="agent-approval-message">{{ card.message }}</p>
    <template v-if="card.kind === 'spend'">
      <dl class="agent-spend">
        <div><dt>People</dt><dd>{{ card.people ?? 'unknown until they exist' }}</dd></div>
        <div><dt>Model calls</dt><dd>{{ card.total_calls ?? 'unknown' }}</dd></div>
        <div><dt>Estimated cost</dt><dd>{{ usd(card.usd_estimate) }}</dd></div>
      </dl>
      <table v-if="steps.length" class="agent-steps">
        <caption>Calls per step</caption>
        <tr v-for="row in steps" :key="row.key"><th scope="row">{{ row.label }}</th><td>{{ row.calls }}</td></tr>
      </table>
      <p class="agent-note">{{ card.estimate_note }}</p>
      <ul v-if="card.notes?.length" class="agent-outside"><li v-for="n in card.notes" :key="n"><Globe :size="12" aria-hidden="true" />Also {{ n }}.</li></ul>
      <div v-if="card.fit_check?.warnings?.length" class="agent-fit" role="note">
        <b>Before you approve</b>
        <p v-for="w in card.fit_check.warnings" :key="w.code">{{ w.text }} <em>{{ w.do_instead }}</em></p>
      </div>
      <label v-if="card.max_spend_usd && !answered" class="agent-cap">Spending cap (US dollars)
        <input v-model="cap" type="number" min="0.01" :max="card.max_spend_usd.max" step="0.5" :disabled="busy" />
        <small>{{ card.max_spend_usd.help }}</small>
      </label>
    </template>
    <div v-if="!answered" class="agent-options">
      <button v-for="(o, i) in card.options" :key="o.value" type="button" :class="{ primary: i === 0 && o.value !== 'stop' && o.value !== 'skip' }" :disabled="busy || capInvalid && o.value !== 'stop'" :title="o.detail || ''" @click="choose(o)">{{ o.label }}</button>
    </div>
    <ul v-if="!answered && details.length" class="agent-option-details">
      <li v-for="o in details" :key="o.value"><b>{{ o.label }}:</b> {{ o.detail }}</li>
    </ul>
    <p v-if="capInvalid" class="agent-tool-error" role="alert">Enter a cap between $0.01 and ${{ card.max_spend_usd.max }}.</p>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { Gauge, Globe, Wallet } from 'lucide-vue-next'
import { answerLabel, stepRows, usd } from '../../../workspace/agentChat.js'
const props = defineProps({ card: { type: Object, required: true }, answered: { type: String, default: null }, busy: Boolean })
const emit = defineEmits(['answer'])
const cap = ref(props.card.max_spend_usd?.suggested ?? '')
const steps = computed(() => stepRows(props.card.steps))
const details = computed(() => (props.card.options || []).filter((o) => o.detail && props.card.kind === 'spend'))
const capInvalid = computed(() => {
  if (!props.card.max_spend_usd || cap.value === '' || cap.value == null) return false
  const v = Number(cap.value)
  return !Number.isFinite(v) || v <= 0 || v > props.card.max_spend_usd.max
})
function choose(option) {
  const answer = props.card.kind === 'limit' ? { choice: option.value } : { decision: option.value }
  if (props.card.max_spend_usd && option.value !== 'stop' && cap.value !== '' && cap.value != null) answer.max_spend_usd = Number(cap.value)
  emit('answer', { pendingId: props.card.id, answer, label: answerLabel(props.card, answer) })
}
</script>
<style scoped src="./agent-cards.css"></style>
