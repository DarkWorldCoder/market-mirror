<template>
  <section class="ovi-panel" aria-labelledby="ovi-obj-heading">
    <div class="ovi-head"><div><h2 id="ovi-obj-heading"><MessageSquareWarning :size="16" aria-hidden="true" />What stops people across all experiments</h2><p>The reasons simulated people gave for not taking the offer, merged across runs.</p></div></div>
    <p v-if="!rows.length" class="ovi-empty">No objections recorded yet. They appear once a run includes a buyer survey.</p>
    <template v-else>
      <ol class="ovi-bars" :aria-label="`Top ${rows.length} objections across runs`">
        <li v-for="(row, i) in rows" :key="row.label">
          <div class="ovi-bar-top"><strong>{{ row.label }}</strong><span>{{ row.runs }} {{ plural(row.runs, { one: 'run', other: 'runs' }) }} · {{ number(row.people) }} {{ plural(row.people, { one: 'person', other: 'people' }) }}</span></div>
          <div class="ovi-bar" aria-hidden="true"><span :style="{ width: widths[i] + '%' }"></span></div>
        </li>
      </ol>
      <p class="ovi-note">Counts are simulated people. The same people can appear in more than one run.</p>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { MessageSquareWarning } from 'lucide-vue-next'
import { barWidths } from '../../../workspace/overviewInsights.js'
import { plural } from '../../../workspace/plural.js'

const props = defineProps({ objections: { type: Array, default: () => [] } })
const rows = computed(() => props.objections.filter((o) => o && o.label).slice(0, 8))
const widths = computed(() => barWidths(rows.value, 'people'))
const number = (v) => new Intl.NumberFormat().format(Number(v) || 0)
</script>
