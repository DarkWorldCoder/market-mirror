<template>
  <section class="ovi-panel" aria-labelledby="ovi-spend-heading">
    <div class="ovi-head"><div><h2 id="ovi-spend-heading"><Wallet :size="16" aria-hidden="true" />Model spend</h2><p>What the AI model calls probably cost, from the spending cap each run recorded. An estimate at list prices, not a bill.</p></div></div>
    <p v-if="!rows.length" class="ovi-empty">No spend recorded yet. Runs started with a spending cap record an estimate here.</p>
    <template v-else>
      <p class="ovi-total"><strong>{{ usd(spend.total_usd) }}</strong><span>estimated across {{ rows.length }} {{ plural(rows.length, { one: 'run', other: 'runs' }) }}</span></p>
      <ol class="ovi-bars" aria-label="Estimated spend per run, highest first">
        <li v-for="(row, i) in rows.slice(0, 8)" :key="row.run">
          <div class="ovi-bar-top"><RouterLink :to="`/workspace/runs/${encodeURIComponent(row.run)}`">{{ row.title || row.run }}</RouterLink><span>{{ usd(row.spent_usd) }}<template v-if="row.limit_usd"> of {{ usd(row.limit_usd) }} cap</template><b v-if="row.reached" class="ovi-tag warn">Cap reached</b></span></div>
          <div class="ovi-bar" aria-hidden="true"><span :style="{ width: widths[i] + '%' }"></span></div>
        </li>
      </ol>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { Wallet } from 'lucide-vue-next'
import { barWidths, usd } from '../../../workspace/overviewInsights.js'
import { plural } from '../../../workspace/plural.js'

const props = defineProps({ spend: { type: Object, required: true } })
const rows = computed(() => props.spend.runs.filter((r) => r && typeof r.spent_usd === 'number'))
const widths = computed(() => barWidths(rows.value.slice(0, 8), 'spent_usd'))
</script>
