<template>
  <div class="rr">
    <p class="rr-intro"><span class="rr-sim">Simulated</span>{{ report.intro }}</p>
    <div v-if="report.cards.length" class="rr-cards" role="list" aria-label="Key numbers">
      <article v-for="c in report.cards" :key="c.label" role="listitem">
        <span>{{ c.label }}</span><strong :title="c.value">{{ c.value }}</strong><small v-if="c.note">{{ c.note }}</small>
      </article>
    </div>
    <section v-for="(s, i) in report.sections" :key="i" class="rr-section" :class="[s.type, { highlight: s.highlight }]">
      <h4>{{ s.title }}</h4>
      <p v-if="s.type === 'summary'" class="rr-summary">{{ s.text }}</p>
      <ul v-else-if="s.type === 'list'" class="rr-list"><li v-for="(item, j) in s.items" :key="j">{{ item }}</li></ul>
      <ol v-else-if="s.type === 'bars'" class="rr-bars">
        <li v-for="(r, j) in shownRows(s, i)" :key="j">
          <span class="rr-bar-label" :title="r.label">{{ r.label }}</span>
          <span class="rr-bar" aria-hidden="true"><i :style="{ width: `${barWidth(s, r)}%` }"></i></span>
          <span class="rr-bar-value">{{ formatValue(r.value, s.unit) }}<small v-if="r.note">{{ r.note }}</small></span>
        </li>
        <li v-if="s.rows.length > 8" class="rr-more-row"><button type="button" @click="toggle(i)">{{ expanded[i] ? 'Show fewer' : `Show all ${s.rows.length}` }}</button></li>
      </ol>
      <div v-else-if="s.type === 'quotes'" class="rr-quotes">
        <blockquote v-for="(q, j) in s.items" :key="j"><p>“{{ q.text }}”</p><footer v-if="q.who">{{ q.who }}</footer></blockquote>
      </div>
      <div v-else-if="s.type === 'cards'" class="rr-item-cards">
        <article v-for="(c, j) in shownCards(s, i)" :key="j">
          <header><b>{{ c.title }}</b><span v-if="c.badge" class="rr-badge">{{ c.badge }}</span></header>
          <small v-if="c.subtitle">{{ c.subtitle }}</small>
          <p v-if="c.body">{{ c.body }}</p>
          <ul v-if="c.bullets?.length"><li v-for="(b, k) in c.bullets" :key="k">{{ b }}</li></ul>
        </article>
        <button v-if="s.items.length > 6" type="button" class="rr-more" @click="toggle(i)">{{ expanded[i] ? 'Show fewer' : `Show all ${s.items.length}` }}</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const props = defineProps({ report: { type: Object, required: true } })
const expanded = reactive({})
const toggle = (i) => (expanded[i] = !expanded[i])
const shownRows = (s, i) => (expanded[i] ? s.rows : s.rows.slice(0, 8))
const shownCards = (s, i) => (expanded[i] ? s.items : s.items.slice(0, 6))
const barWidth = (s, r) => {
  const max = s.unit === '%' ? Math.max(100, ...s.rows.map((x) => x.value || 0)) : Math.max(1, ...s.rows.map((x) => x.value || 0))
  return Math.max(1.5, ((r.value || 0) / max) * 100)
}
const formatValue = (v, unit) => `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(v || 0)}${unit || ''}`
void props
</script>

<style scoped>
.rr { display: grid; gap: 16px; font-size: 13.5px; line-height: 1.6; min-width: 0; }
.rr-intro { margin: 0; color: var(--muted); display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.rr-sim { font-size: 10.5px; color: var(--warm); border: 1px solid color-mix(in srgb, var(--warm) 45%, var(--line)); border-radius: 999px; padding: 0 7px; flex: none; }
.rr-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
.rr-cards article { padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel-2); min-width: 0; }
.rr-cards span { display: block; font-size: 11.5px; color: var(--muted); }
.rr-cards strong { display: block; font-size: 20px; font-weight: 600; line-height: 1.3; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rr-cards small { display: block; font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.rr-section h4 { margin: 0 0 8px; font-size: 13px; font-weight: 650; }
.rr-section.highlight { padding: 12px 14px; border-radius: 12px; background: var(--accent-2); border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent); }
.rr-summary { margin: 0; white-space: pre-line; overflow-wrap: anywhere; }
.rr-list { margin: 0; padding-left: 18px; display: grid; gap: 4px; }
.rr-list li { overflow-wrap: anywhere; }
.rr-bars { list-style: none; padding: 0; margin: 0; display: grid; gap: 7px; }
.rr-bars li { display: grid; grid-template-columns: minmax(90px, 38%) minmax(0, 1fr) auto; gap: 10px; align-items: center; font-size: 12.5px; }
.rr-bar-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rr-bar { height: 8px; border-radius: 999px; background: var(--panel-2); overflow: hidden; }
.rr-bar i { display: block; height: 100%; border-radius: inherit; background: var(--accent); }
.rr-bar-value { font-variant-numeric: tabular-nums; font-weight: 600; text-align: right; white-space: nowrap; }
.rr-bar-value small { display: block; font-weight: 400; font-size: 11px; color: var(--muted); }
.rr-more-row { display: block !important; }
.rr-more-row button, .rr-more { border: 0; background: none; color: var(--accent); cursor: pointer; padding: 2px 0; font-size: 12.5px; }
.rr-quotes { display: grid; gap: 8px; }
.rr-quotes blockquote { margin: 0; padding: 10px 12px; border-left: 3px solid var(--accent); background: var(--panel-2); border-radius: 8px; }
.rr-quotes p { margin: 0; font-style: italic; overflow-wrap: anywhere; }
.rr-quotes footer { margin-top: 4px; font-size: 11.5px; color: var(--muted); }
.rr-item-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.rr-item-cards article { padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); min-width: 0; }
.rr-item-cards header { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.rr-item-cards b { font-size: 13.5px; overflow-wrap: anywhere; }
.rr-badge { flex: none; font-size: 11px; border: 1px solid var(--line); border-radius: 999px; padding: 0 8px; color: var(--muted); }
.rr-item-cards small { display: block; color: var(--muted); font-size: 11.5px; margin-top: 2px; }
.rr-item-cards p { margin: 6px 0 0; overflow-wrap: anywhere; }
.rr-item-cards ul { margin: 6px 0 0; padding-left: 16px; font-size: 12.5px; color: var(--muted); }
.rr-item-cards li { overflow-wrap: anywhere; }
.rr-more { grid-column: 1 / -1; justify-self: start; }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
@media (max-width: 600px) { .rr-bars li { grid-template-columns: 1fr auto; } .rr-bar { grid-column: 1 / -1; grid-row: 2; } }
</style>
