<template>
  <section class="agent-card" :aria-label="card.title || 'A few details'">
    <header><ClipboardList :size="16" aria-hidden="true" /><b>{{ card.title || 'A few details' }}</b><span v-if="answered" class="agent-answered">{{ answered }}</span></header>
    <p v-if="card.reason" class="agent-approval-message">{{ card.reason }}</p>
    <form v-if="!answered" class="agent-form" @submit.prevent="submit">
      <label v-for="f in card.fields" :key="f.name">{{ f.label }}<template v-if="!f.required"> (optional)</template>
        <select v-if="f.type === 'select'" v-model="values[f.name]" :disabled="busy">
          <option value="">Choose…</option>
          <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <textarea v-else-if="f.type === 'textarea' || f.type === 'list'" v-model="values[f.name]" rows="3" :disabled="busy" :placeholder="f.type === 'list' ? 'One per line' : ''" />
        <input v-else v-model="values[f.name]" :type="f.type === 'number' ? 'number' : 'text'" :disabled="busy" />
        <small v-if="tried && errors[f.name]">{{ errors[f.name] }}</small>
      </label>
      <div class="agent-actions">
        <button type="submit" class="primary" :disabled="busy">Send</button>
        <button type="button" :disabled="busy" @click="emit('answer', { pendingId: card.id, answer: { cancel: true }, label: 'Cancelled' })">Cancel</button>
      </div>
    </form>
  </section>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import { ClipboardList } from 'lucide-vue-next'
import { formErrors } from '../../../workspace/agentChat.js'
const props = defineProps({ card: { type: Object, required: true }, answered: { type: String, default: null }, busy: Boolean })
const emit = defineEmits(['answer'])
const values = reactive(Object.fromEntries((props.card.fields || []).map((f) => [f.name, ''])))
const tried = ref(false)
const errors = computed(() => formErrors(props.card.fields, values))
function submit() {
  tried.value = true
  if (Object.keys(errors.value).length) return
  emit('answer', { pendingId: props.card.id, answer: { values: { ...values } }, label: 'Sent' })
}
</script>
<style scoped src="./agent-cards.css"></style>
