<template>
  <details class="agent-tool" :class="card.status" :open="card.status === 'running' || card.status === 'failed'">
    <summary>
      <LoaderCircle v-if="card.status === 'running'" class="spin" :size="14" aria-hidden="true" />
      <CircleCheck v-else-if="card.status === 'completed'" :size="14" aria-hidden="true" />
      <CircleSlash v-else-if="card.status === 'declined'" :size="14" aria-hidden="true" />
      <CircleAlert v-else :size="14" aria-hidden="true" />
      <b>{{ card.label || card.tool }}</b>
      <span class="agent-tool-cost" :class="card.cost">{{ costLabel(card.cost) }}</span>
      <SimulatedBadge v-if="simulated && card.status === 'completed'" />
      <small>{{ statusText }}</small>
    </summary>
    <div class="agent-tool-body">
      <p v-if="card.error" class="agent-tool-error" role="alert">{{ card.error }}</p>
      <template v-if="hasArgs">
        <h4>Arguments</h4>
        <pre>{{ argsPreview(card.args) }}</pre>
      </template>
      <template v-if="card.log?.length">
        <h4>Latest log lines<span v-if="card.elapsed_s != null"> · {{ card.elapsed_s }} s</span></h4>
        <pre class="agent-tool-log" aria-live="polite">{{ lastLines(card.log, 15).join('\n') }}</pre>
      </template>
      <template v-if="card.preview">
        <h4>Result</h4>
        <pre>{{ card.preview }}</pre>
      </template>
    </div>
  </details>
</template>
<script setup>
import { computed } from 'vue'
import { CircleAlert, CircleCheck, CircleSlash, LoaderCircle } from 'lucide-vue-next'
import SimulatedBadge from './SimulatedBadge.vue'
import { argsPreview, costLabel, durationText, isSimulated, lastLines } from '../../../workspace/agentChat.js'
const props = defineProps({ card: { type: Object, required: true } })
const simulated = computed(() => isSimulated(props.card.tool, props.card.simulated))
const hasArgs = computed(() => props.card.args && Object.keys(props.card.args).length > 0)
const statusText = computed(() => {
  const c = props.card
  if (c.status === 'running') return c.elapsed_s != null ? `running · ${c.elapsed_s} s` : 'running'
  if (c.status === 'declined') return 'declined, nothing ran'
  if (c.status === 'failed') return 'failed'
  return durationText(c.duration_ms) || 'done'
})
</script>
<style scoped>
.agent-tool { margin: 8px 0; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); font-size: 12px; }
.agent-tool summary { display: flex; align-items: center; gap: 8px; padding: 9px 12px; cursor: pointer; list-style: none; }
.agent-tool summary::-webkit-details-marker { display: none; }
.agent-tool summary b { font-weight: 550; }
.agent-tool summary small { margin-left: auto; color: var(--muted); }
.agent-tool.completed summary > svg { color: var(--accent); }
.agent-tool.failed summary > svg { color: #c2410c; }
.agent-tool-cost { padding: 1px 7px; border-radius: 999px; font-size: 10px; color: var(--muted); border: 1px solid var(--line); }
.agent-tool-cost.spend { border-color: color-mix(in srgb, var(--accent) 50%, var(--line)); color: var(--text); }
.agent-tool-body { padding: 0 12px 10px; }
.agent-tool-body h4 { margin: 10px 0 4px; font-size: 11px; font-weight: 550; color: var(--muted); }
.agent-tool-body pre { margin: 0; padding: 8px 10px; max-height: 220px; overflow: auto; border-radius: 8px; background: var(--panel-2); font-size: 11px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-tool-error { margin-top: 8px; color: #c2410c; line-height: 1.6; }
.spin { animation: agent-spin 1.4s linear infinite; }
@keyframes agent-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
