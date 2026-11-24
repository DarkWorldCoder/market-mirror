<template>
  <section class="agent-card agent-audience" aria-label="Audience design">
    <header><UsersRound :size="16" aria-hidden="true" /><b>{{ card.title || 'Review the audience' }}</b><SimulatedBadge /><span v-if="answered" class="agent-answered">{{ answered }}</span></header>
    <p class="agent-approval-message">These simulated people are created only after you approve the test's spend. Edit anything; the cost updates as you type.</p>
    <div class="agent-audience-scroll">
      <table>
        <thead><tr><th>Segment</th><th>People</th><th>Country</th><th>Cities</th><th>Ages</th><th>Gender mix</th><th>Platforms</th><th>Communities</th><th>Notes</th><th v-if="!answered"><span class="sr-only">Remove</span></th></tr></thead>
        <tbody>
          <tr v-for="(s, i) in rows" :key="i">
            <td><input v-model="s.label" :disabled="locked" aria-label="Segment label" placeholder="Busy parents" /></td>
            <td><input v-model.number="s.count" type="number" min="1" max="200" :disabled="locked" aria-label="People" class="num" /></td>
            <td><input v-model="s.country" :disabled="locked" aria-label="Country" placeholder="India" /></td>
            <td><input :value="listText(s.cities)" :disabled="locked" aria-label="Cities" placeholder="Mumbai, Pune" @change="s.cities = parseList($event.target.value)" /></td>
            <td class="ages"><input v-model.number="s.age_min" type="number" min="10" max="100" :disabled="locked" aria-label="Youngest age" class="num" />–<input v-model.number="s.age_max" type="number" min="10" max="100" :disabled="locked" aria-label="Oldest age" class="num" /></td>
            <td><select v-model="s.gender_mix" :disabled="locked" aria-label="Gender mix"><option value="balanced">Balanced</option><option value="female">Mostly women</option><option value="male">Mostly men</option></select></td>
            <td><input :value="listText(s.platforms)" :disabled="locked" aria-label="Platforms" placeholder="instagram, android" @change="s.platforms = parseList($event.target.value)" /></td>
            <td><input :value="listText(s.communities)" :disabled="locked" aria-label="Communities" placeholder="Parents of Pune" @change="s.communities = parseList($event.target.value)" /></td>
            <td><input v-model="s.notes" :disabled="locked" aria-label="Notes" placeholder="What you know about them" /></td>
            <td v-if="!answered"><button type="button" :disabled="locked || rows.length < 2" aria-label="Remove segment" @click="rows.splice(i, 1)"><X :size="14" /></button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <button v-if="!answered" type="button" class="agent-add" :disabled="locked" @click="rows.push(blankSegment())"><Plus :size="13" />Add segment</button>
    <dl class="agent-spend">
      <div><dt>People</dt><dd>{{ totals.people }}</dd></div>
      <div><dt>Calls to create them and run a survey</dt><dd>{{ estimate?.total_calls ?? '…' }}</dd></div>
      <div><dt>Estimated cost</dt><dd>{{ usd(estimate?.usd_estimate) }}</dd></div>
    </dl>
    <div v-if="flags.length" class="agent-fit" role="note">
      <b>Flags before approval</b>
      <p v-for="f in flags" :key="f.code">{{ f.text }} <em v-if="f.do_instead">{{ f.do_instead }}</em></p>
    </div>
    <p v-if="problem" class="agent-tool-error" role="alert">{{ problem }}</p>
    <div v-if="!answered" class="agent-actions">
      <button type="button" class="primary" :disabled="busy || !!problem || !totals.segments" @click="confirm">Use this audience</button>
      <button type="button" :disabled="busy" @click="emit('answer', { pendingId: card.id, answer: { cancel: true }, label: 'Cancelled' })">Cancel</button>
    </div>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Plus, UsersRound, X } from 'lucide-vue-next'
import SimulatedBadge from './SimulatedBadge.vue'
import { api } from '../../../workspace/api.js'
import { blankSegment, listText, parseList, segmentFlags, segmentTotals, usd } from '../../../workspace/agentChat.js'
const props = defineProps({ card: { type: Object, required: true }, answered: { type: String, default: null }, busy: Boolean })
const emit = defineEmits(['answer'])
const rows = ref((props.card.segments || []).map((s) => ({ ...blankSegment(), ...s })))
const estimate = ref(props.card.estimate || null), serverFlags = ref(props.card.fit_check?.warnings || null), problem = ref('')
const locked = computed(() => props.busy || !!props.answered)
const totals = computed(() => segmentTotals(rows.value))
const flags = computed(() => serverFlags.value ?? segmentFlags(rows.value))
let timer = null, ticket = 0
watch(rows, () => {
  if (props.answered) return
  serverFlags.value = null
  clearTimeout(timer)
  timer = setTimeout(refresh, 400)
}, { deep: true })
async function refresh() {
  const mine = ++ticket
  try {
    const data = await api('/api/workspace/agent/audience/estimate', { method: 'POST', body: { segments: rows.value } })
    if (mine !== ticket) return
    estimate.value = data.estimate; serverFlags.value = data.fit_check?.warnings || []; problem.value = ''
  } catch (e) { if (mine === ticket) problem.value = e.message }
}
function confirm() {
  emit('answer', { pendingId: props.card.id, answer: { segments: rows.value.filter((s) => String(s.label || '').trim()) }, label: 'Audience confirmed' })
}
onBeforeUnmount(() => clearTimeout(timer))
</script>
<style scoped src="./agent-cards.css"></style>
<style scoped>
.agent-audience-scroll { overflow-x: auto; margin: 8px 0; }
.agent-audience table { border-collapse: collapse; font-size: 12px; min-width: 860px; width: 100%; }
.agent-audience th { text-align: left; font-weight: 550; font-size: 11px; color: var(--muted); padding: 4px 4px 6px; }
.agent-audience td { padding: 3px 4px; border-top: 1px solid var(--line); }
.agent-audience td input, .agent-audience td select { width: 100%; min-width: 70px; padding: 6px 7px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel-2); color: var(--text); font: inherit; }
.agent-audience td input.num { min-width: 48px; width: 56px; }
.agent-audience td.ages { white-space: nowrap; }
.agent-audience td button { border: 0; background: none; color: var(--muted); cursor: pointer; padding: 4px; }
.agent-add { display: inline-flex; align-items: center; gap: 5px; border: 1px dashed var(--line); border-radius: 8px; background: none; color: var(--muted); padding: 5px 10px; font-size: 12px; cursor: pointer; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
