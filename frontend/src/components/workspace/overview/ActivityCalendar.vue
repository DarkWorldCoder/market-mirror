<template>
  <section class="ovi-panel" aria-labelledby="ovi-cal-heading">
    <div class="ovi-head">
      <div><h2 id="ovi-cal-heading"><CalendarDays :size="16" aria-hidden="true" />When you ran experiments</h2><p>Saved runs per day over the last six months. Pick a day to see its runs in the table below.</p></div>
      <button v-if="selected" type="button" class="ovi-chip" @click="$emit('select-day', '')"><X :size="13" aria-hidden="true" />Clear day</button>
    </div>
    <p v-if="!cal.shown" class="ovi-empty">No runs in the last six months<template v-if="cal.earlier">; {{ cal.earlier }} older {{ plural(cal.earlier, { one: 'run is', other: 'runs are' }) }} still in the table</template>.</p>
    <template v-else>
      <div class="ovi-cal-scroll" tabindex="0" role="region" aria-label="Runs per day calendar, scrolls sideways">
        <div class="ovi-cal-months" aria-hidden="true"><span v-for="m in cal.months" :key="m.index" :style="{ gridColumn: `${m.index + 1} / span ${Math.max(1, Math.min(3, cal.weeks.length - m.index))}` }">{{ m.label }}</span></div>
        <div class="ovi-cal" role="group" :aria-label="`Runs per day, ${cal.shown} runs over the last six months. Days with runs are buttons.`" @mouseleave="hover = null">
          <div v-for="(week, w) in cal.weeks" :key="w" class="ovi-cal-week">
            <template v-for="cell in week" :key="cell.date">
              <button v-if="cell.count" type="button" class="ovi-cal-cell" :class="[`l${cell.level}`, { selected: cell.date === selected }]" :aria-label="dayLabel(cell)" :aria-pressed="cell.date === selected" :title="dayLabel(cell)" :data-cal-date="cell.date" :tabindex="cell.date === focusDate ? 0 : -1" @click="$emit('select-day', cell.date === selected ? '' : cell.date)" @keydown="onKeydown($event, cell)" @mouseenter="hover = cell" @focus="focusDate = cell.date; hover = cell" @blur="hover = null"></button>
              <span v-else class="ovi-cal-cell l0" :class="{ future: cell.future }" :title="cell.future ? '' : dayLabel(cell)" aria-hidden="true" @mouseenter="hover = cell.future ? null : cell"></span>
            </template>
          </div>
        </div>
      </div>
      <div class="ovi-cal-foot">
        <p class="ovi-note" aria-live="polite">{{ hover ? dayLabel(hover) + (hover.runs?.length ? ': ' + hover.runs.slice(0, 3).join(', ') + (hover.runs.length > 3 ? ` and ${hover.runs.length - 3} more` : '') : '') : `${cal.shown} ${plural(cal.shown, { one: 'run', other: 'runs' })} in this period` + (cal.earlier ? `, ${cal.earlier} earlier` : '') }}</p>
        <span class="ovi-cal-legend" aria-hidden="true">Fewer<i class="ovi-cal-cell l0"></i><i class="ovi-cal-cell l1"></i><i class="ovi-cal-cell l2"></i><i class="ovi-cal-cell l3"></i><i class="ovi-cal-cell l4"></i>More</span>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { CalendarDays, X } from 'lucide-vue-next'
import { calendarWeeks, dayLabel } from '../../../workspace/overviewInsights.js'
import { plural } from '../../../workspace/plural.js'

const props = defineProps({ activity: { type: Array, default: () => [] }, selected: { type: String, default: '' } })
defineEmits(['select-day'])
const hover = ref(null)
const cal = computed(() => calendarWeeks(props.activity, new Date(), 26))
const focusDate = ref('')
const activeDays = computed(() => cal.value.weeks.flat().filter(cell => cell.count))
watch(activeDays, (days) => {
  if (!days.some(cell => cell.date === focusDate.value)) focusDate.value = days[0]?.date || ''
}, { immediate: true })

function shiftDate(date, days) {
  const value = new Date(`${date}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}
// One tab stop for the calendar; arrows move by day or week, Home/End jump to
// the range's ends, Enter selects the focused day.
function onKeydown(event, cell) {
  if (event.key === 'Enter' || event.key === ' ') return
  const byDate = new Map(cal.value.weeks.flat().map(day => [day.date, day]))
  let target = null
  if (event.key === 'ArrowUp') target = shiftDate(cell.date, -1)
  else if (event.key === 'ArrowDown') target = shiftDate(cell.date, 1)
  else if (event.key === 'ArrowLeft') target = shiftDate(cell.date, -7)
  else if (event.key === 'ArrowRight') target = shiftDate(cell.date, 7)
  else if (event.key === 'Home') target = activeDays.value[0]?.date
  else if (event.key === 'End') target = activeDays.value[activeDays.value.length - 1]?.date
  else return
  if (event.key === 'ArrowUp' || event.key === 'ArrowDown' || event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    const step = event.key === 'ArrowLeft' ? -7 : event.key === 'ArrowRight' ? 7 : event.key === 'ArrowUp' ? -1 : 1
    while (target && byDate.get(target) && !byDate.get(target).count) target = shiftDate(target, step)
  }
  if (!target || !byDate.get(target)?.count) return
  event.preventDefault()
  focusDate.value = target
  nextTick(() => document.querySelector(`[data-cal-date="${target}"]`)?.focus())
}
</script>
