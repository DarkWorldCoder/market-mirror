<template>
  <section class="ovi-panel" aria-labelledby="ovi-cal-heading">
    <div class="ovi-head">
      <div><h2 id="ovi-cal-heading"><CalendarDays :size="16" aria-hidden="true" />When you ran experiments</h2><p>Saved runs per day over the last six months. Pick a day to see its runs in the table below.</p></div>
      <button v-if="selected" type="button" class="ovi-chip" @click="$emit('select-day', '')"><X :size="13" aria-hidden="true" />Clear day</button>
    </div>
    <p v-if="!cal.shown" class="ovi-empty">No runs in the last six months<template v-if="cal.earlier">; {{ cal.earlier }} older {{ cal.earlier === 1 ? 'run is' : 'runs are' }} still in the table</template>.</p>
    <template v-else>
      <div class="ovi-cal-scroll" tabindex="0" role="region" aria-label="Runs per day calendar, scrolls sideways">
        <div class="ovi-cal-months" aria-hidden="true"><span v-for="m in cal.months" :key="m.index" :style="{ gridColumn: `${m.index + 1} / span ${Math.max(1, Math.min(3, cal.weeks.length - m.index))}` }">{{ m.label }}</span></div>
        <div class="ovi-cal" role="group" :aria-label="`Runs per day, ${cal.shown} runs over the last six months. Days with runs are buttons.`" @mouseleave="hover = null">
          <div v-for="(week, w) in cal.weeks" :key="w" class="ovi-cal-week">
            <template v-for="cell in week" :key="cell.date">
              <button v-if="cell.count" type="button" class="ovi-cal-cell" :class="[`l${cell.level}`, { selected: cell.date === selected }]" :aria-label="dayLabel(cell)" :aria-pressed="cell.date === selected" :title="dayLabel(cell)" @click="$emit('select-day', cell.date === selected ? '' : cell.date)" @mouseenter="hover = cell" @focus="hover = cell" @blur="hover = null"></button>
              <span v-else class="ovi-cal-cell l0" :class="{ future: cell.future }" :title="cell.future ? '' : dayLabel(cell)" aria-hidden="true" @mouseenter="hover = cell.future ? null : cell"></span>
            </template>
          </div>
        </div>
      </div>
      <div class="ovi-cal-foot">
        <p class="ovi-note" aria-live="polite">{{ hover ? dayLabel(hover) + (hover.runs?.length ? ': ' + hover.runs.slice(0, 3).join(', ') + (hover.runs.length > 3 ? ` and ${hover.runs.length - 3} more` : '') : '') : `${cal.shown} ${cal.shown === 1 ? 'run' : 'runs'} in this period` + (cal.earlier ? `, ${cal.earlier} earlier` : '') }}</p>
        <span class="ovi-cal-legend" aria-hidden="true">Fewer<i class="ovi-cal-cell l0"></i><i class="ovi-cal-cell l1"></i><i class="ovi-cal-cell l2"></i><i class="ovi-cal-cell l3"></i><i class="ovi-cal-cell l4"></i>More</span>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { CalendarDays, X } from 'lucide-vue-next'
import { calendarWeeks, dayLabel } from '../../../workspace/overviewInsights.js'

const props = defineProps({ activity: { type: Array, default: () => [] }, selected: { type: String, default: '' } })
defineEmits(['select-day'])
const hover = ref(null)
const cal = computed(() => calendarWeeks(props.activity, new Date(), 26))
</script>
