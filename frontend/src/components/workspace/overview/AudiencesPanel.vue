<template>
  <section class="ovi-panel" aria-labelledby="ovi-aud-heading">
    <div class="ovi-head"><div><h2 id="ovi-aud-heading"><UsersRound :size="16" aria-hidden="true" />Audiences you keep testing</h2><p>Groups of simulated people that came up in the most runs, with the share who said they would take the offer.</p></div></div>
    <p v-if="!rows.length" class="ovi-empty">No audience groups recorded yet.</p>
    <template v-else>
      <ol class="ovi-bars" :aria-label="`${rows.length} audience groups, most frequent first`">
        <li v-for="(row, i) in rows" :key="row.segment">
          <div class="ovi-bar-top"><strong>{{ row.segment }}</strong><span>{{ row.rate == null ? 'No survey rate' : `${pct(row.rate)} said yes` }}</span></div>
          <div class="ovi-bar" aria-hidden="true"><span :style="{ width: widths[i] + '%' }"></span></div>
          <small class="ovi-bar-meta">In {{ row.runs }} {{ row.runs === 1 ? 'run' : 'runs' }} · {{ number(row.people) }} simulated {{ row.people === 1 ? 'person' : 'people' }}</small>
        </li>
      </ol>
      <p class="ovi-note">Bars show how many runs included the group. Rates are simulated and weighted by group size.</p>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { UsersRound } from 'lucide-vue-next'
import { barWidths, pct } from '../../../workspace/overviewInsights.js'

const props = defineProps({ segments: { type: Array, default: () => [] } })
const rows = computed(() => props.segments.filter((s) => s && s.segment).slice(0, 8))
const widths = computed(() => barWidths(rows.value, 'runs'))
const number = (v) => new Intl.NumberFormat().format(Number(v) || 0)
</script>
