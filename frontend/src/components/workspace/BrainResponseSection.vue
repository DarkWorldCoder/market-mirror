<template>
  <section class="ws-brain" aria-labelledby="ws-brain-title">
    <h3 id="ws-brain-title">Predicted brain response (research)</h3>
    <p class="ws-note">{{ BRAIN_LABEL }}</p>
    <p class="ws-note">Each line is a group of brain areas, z-scored within the ad (0 is the ad's own average), so compare the shape over time, not the height between ads. Shown beside the simulated buyers; never given to them.</p>
    <div class="ws-brain-grid">
      <div v-for="r in rows" :key="r.id" class="ws-box">
        <h4>{{ r.id }}<template v-if="r.name"> · {{ r.name }}</template><span v-if="r.kind" class="pill">{{ r.kind }}</span></h4>
        <template v-if="r.status === 'ok' && r.summary">
          <EChart v-if="brainOption(r.summary)" :option="brainOption(r.summary)" :height="190" :label="`Predicted brain response for ${r.id}`" :theme="theme" />
          <p class="ws-note">{{ r.line }}</p>
          <p v-if="peakText(r.summary).length" class="ws-note">Peaks (seconds into the ad): {{ peakText(r.summary).join(' · ') }}</p>
        </template>
        <p v-else class="ws-note">Skipped: {{ r.reason || 'no prediction' }}</p>
      </div>
    </div>
    <p v-if="timing" class="ws-note">Timing check: {{ timing }}</p>
    <p v-if="lag" class="ws-note">{{ lag }} Atlas: Destrieux (nilearn, fsaverage5). Model: facebook/tribev2, CC BY-NC 4.0.</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import EChart from './EChart.vue'
import { BRAIN_LABEL, brainOption, brainRows, peakText } from '../../workspace/brainResponse.js'

const props = defineProps({ brain: { type: Object, default: null }, feed: { type: Object, default: null }, theme: { type: String, default: 'light' } })
const rows = computed(() => brainRows(props.brain, props.feed))
const timing = computed(() => {
  const tc = props.brain?.timing_check || {}
  if (tc.status === 'ok') return `${tc.near_peak} of ${tc.references} simulated reactions that name a moment fall within ${tc.tolerance_s ?? 2} s of a predicted peak. ${tc.note || ''}`
  return tc.note || ''
})
const lag = computed(() => rows.value.find((r) => r.summary?.lag_note)?.summary.lag_note || '')
</script>

<style scoped>
.ws-brain { margin: 18px 0; }
.ws-brain h3 { margin: 0 0 4px; }
.ws-brain h4 { margin: 0 0 6px; font-size: 13px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.ws-brain-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin: 10px 0; }
.ws-brain .pill { font-size: 11px; font-weight: 500; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); }
</style>
