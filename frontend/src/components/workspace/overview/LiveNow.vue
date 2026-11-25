<template>
  <section v-if="runs.length" class="ovi-panel ovi-live" aria-labelledby="ovi-live-heading">
    <div class="ovi-head"><div><h2 id="ovi-live-heading"><Radio :size="16" aria-hidden="true" />Live now</h2><p>Runs that are working right now. This updates every 10 seconds while something is running.</p></div></div>
    <p class="sr-only" aria-live="polite">{{ announcement }}</p>
    <ul class="ovi-live-list">
      <li v-for="run in runs" :key="run.name">
        <span class="ovi-live-dot" aria-hidden="true"></span>
        <RouterLink :to="`/workspace/runs/${encodeURIComponent(run.name)}`">{{ run.title || run.name }}</RouterLink>
        <span class="ovi-live-stage">{{ liveStage(statuses[run.name], run) }}</span>
        <progress v-if="progress(run) !== null" :value="progress(run)" max="100" :aria-label="`${run.title || run.name} progress`"></progress>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Radio } from 'lucide-vue-next'
import { api } from '../../../workspace/api.js'
import { liveProgress, liveStage, stillRunning } from '../../../workspace/overviewInsights.js'

const props = defineProps({ runs: { type: Array, default: () => [] } })
const emit = defineEmits(['changed'])
const statuses = reactive({})
const announcement = ref('')
const progress = (run) => liveProgress(statuses[run.name], run)
let timer = null, busy = false

async function poll() {
  if (busy || document.hidden || !props.runs.length) return
  busy = true
  let finished = false
  const changes = []
  try {
    await Promise.all(props.runs.map(async (run) => {
      try {
        const s = await api(`/api/runs/${encodeURIComponent(run.name)}/status`)
        const before = statuses[run.name]
        statuses[run.name] = s
        if (before && liveStage(before, run) !== liveStage(s, run)) changes.push(`${run.title || run.name} is now ${liveStage(s, run)}`)
        if (before && stillRunning(before) && !stillRunning(s)) {
          changes.push(`${run.title || run.name} finished`)
          window.dispatchEvent(new CustomEvent('mm-run-finished', { detail: { name: run.name, title: run.title || run.name } }))
        }
        if (!stillRunning(s)) finished = true
      } catch { /* keep the last known stage; the next poll retries */ }
    }))
  } finally {
    busy = false
  }
  if (changes.length) announcement.value = changes.join('. ')
  if (finished) emit('changed')
}
function stop() { if (timer) { clearInterval(timer); timer = null } }
watch(() => props.runs.map((r) => r.name).join('|'), (names) => {
  stop()
  if (names) { poll(); timer = setInterval(poll, 10000) }
}, { immediate: true })
onBeforeUnmount(stop)
</script>
