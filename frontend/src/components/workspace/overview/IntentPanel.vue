<template>
  <section class="ovi-panel" aria-labelledby="ovi-intent-heading">
    <div class="ovi-head"><div><h2 id="ovi-intent-heading"><Target :size="16" aria-hidden="true" />Buying intent across runs</h2><p>Share of simulated people who said they would take the offer. The bar shows the likely range for that many people.</p></div></div>
    <p v-if="!data.rows.length" class="ovi-empty">No run has a buyer survey yet, so there is no buying intent to compare.</p>
    <template v-else>
      <ul class="ovi-intent-list" :aria-label="`Simulated buying intent for ${data.total} runs, newest first`">
        <li v-for="row in data.rows" :key="row.run">
          <RouterLink class="ovi-intent-row" :to="`/workspace/runs/${encodeURIComponent(row.run)}`" :aria-label="`${row.title || row.run}: ${pct(row.rate)} said yes out of ${row.n} simulated people, likely range ${pct(row.low)} to ${pct(row.high)}${row.small ? ', small sample' : ''}. Open run.`">
            <span class="ovi-intent-name"><strong>{{ row.title || row.run }}</strong><small>{{ row.date || 'No date' }} · {{ row.n }} people<span v-if="row.small" class="ovi-tag warn">Small sample</span></small></span>
            <span class="ovi-track" aria-hidden="true"><span class="ovi-range" :style="{ left: position(row.low, data.axis) + '%', width: Math.max(0.8, position(row.high, data.axis) - position(row.low, data.axis)) + '%' }"></span><span class="ovi-dot" :class="{ hollow: row.small }" :style="{ left: position(row.rate, data.axis) + '%' }"></span></span>
            <span class="ovi-intent-value"><strong>{{ pct(row.rate) }}</strong><small>{{ pct(row.low) }}–{{ pct(row.high) }}</small></span>
          </RouterLink>
        </li>
      </ul>
      <div class="ovi-axis" aria-hidden="true"><span>0%</span><span>{{ data.axis }}%</span></div>
      <button v-if="data.total > limit" type="button" class="ovi-more" :aria-expanded="all" @click="all = !all">{{ all ? 'Show fewer' : `Show all ${data.total} runs` }}</button>
      <p class="ovi-note">Simulated answers. Hollow dots mark runs with fewer than 30 people, where the range is wide.</p>
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Target } from 'lucide-vue-next'
import { intentRows, pct, position } from '../../../workspace/overviewInsights.js'

const props = defineProps({ intent: { type: Array, default: () => [] } })
const limit = 8
const all = ref(false)
const data = computed(() => intentRows(props.intent, all.value ? Infinity : limit))
</script>
