// Pure helpers for the workspace overview panels fed by GET /api/runs/insights. No DOM, no fetch: the components
// call these and the unit tests cover them. Every number is about simulated people; the panels say so.

const pad = (n) => String(n).padStart(2, '0')
/** A Date -> 'YYYY-MM-DD' in local time (the backend writes run dates the same way). */
export const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const finite = (v) => typeof v === 'number' && Number.isFinite(v)

export const EMPTY_INSIGHTS = Object.freeze({
  total_runs: 0, runs: [], activity: [], decisions: { go: 0, iterate: 0, no_go: 0, unrecorded: 0 }, intent: [],
  objections: [], segments: [],
  geography: { countries: [], cities: [], people_with_country: 0, runs_with_places: 0 },
  trust: { runs: [], graded: 0, calibrated: 0, grades: {} },
  spend: { runs: [], total_usd: 0, estimate: true },
  forecasts: { locked: 0, scored: 0, hits: 0, checks: 0, entries: [] },
  running: []
})

const arr = (v) => (Array.isArray(v) ? v : [])
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {})

/** The API payload with every key the panels read present and of the right type. */
export function normalizeInsights(data) {
  const d = obj(data), e = EMPTY_INSIGHTS
  const geo = obj(d.geography), trust = obj(d.trust), spend = obj(d.spend), fc = obj(d.forecasts)
  return {
    ...e,
    total_runs: finite(d.total_runs) ? d.total_runs : 0,
    runs: arr(d.runs), activity: arr(d.activity), intent: arr(d.intent), objections: arr(d.objections),
    segments: arr(d.segments), running: arr(d.running),
    decisions: { ...e.decisions, ...obj(d.decisions) },
    geography: { ...e.geography, ...geo, countries: arr(geo.countries), cities: arr(geo.cities) },
    trust: { ...e.trust, ...trust, runs: arr(trust.runs), grades: obj(trust.grades) },
    spend: { ...e.spend, ...spend, runs: arr(spend.runs), total_usd: finite(spend.total_usd) ? spend.total_usd : 0 },
    forecasts: { ...e.forecasts, ...fc, entries: arr(fc.entries) }
  }
}

/** Intensity 0-4 for a day with `count` runs, relative to the busiest day. */
export function activityLevel(count, max) {
  if (!finite(count) || count <= 0) return 0
  if (!finite(max) || max <= 1) return 4
  return Math.min(4, Math.max(1, Math.ceil((count / max) * 4)))
}

/**
 * A contribution-style calendar: `weeks` columns ending with the week that holds `end`, each 7 cells Sunday first.
 * Returns { weeks: [[{date, count, runs, level, future}]], months: [{index, label}], max, shown, earlier }.
 * `earlier` counts runs dated before the first cell; `shown` the runs inside the grid.
 */
export function calendarWeeks(activity, end = new Date(), weeks = 26, locale = undefined) {
  const byDay = new Map()
  for (const a of arr(activity)) if (a && typeof a.date === 'string') byDay.set(a.date, a)
  const last = new Date(end.getFullYear(), end.getMonth(), end.getDate())
  const start = new Date(last)
  start.setDate(start.getDate() - start.getDay() - (weeks - 1) * 7)
  const today = dayKey(last), first = dayKey(start)
  let max = 0
  for (const [date, a] of byDay) if (date >= first && date <= today) max = Math.max(max, Number(a.count) || 0)
  const cols = [], months = []
  const month = new Intl.DateTimeFormat(locale, { month: 'short' })
  let shown = 0
  for (let w = 0; w < weeks; w++) {
    const col = []
    for (let d = 0; d < 7; d++) {
      const day = new Date(start)
      day.setDate(start.getDate() + w * 7 + d)
      const date = dayKey(day), a = byDay.get(date), count = Number(a?.count) || 0
      if (day.getDate() === 1 || (w === 0 && d === 0)) months.push({ index: w, label: month.format(day) })
      const future = date > today
      if (!future) shown += count
      col.push({ date, count: future ? 0 : count, runs: future ? [] : arr(a?.runs), level: future ? 0 : activityLevel(count, max), future })
    }
    cols.push(col)
  }
  // keep one label per column, and drop a first-column label that would collide with the next month
  const seen = new Set(), labels = []
  for (const m of months) if (!seen.has(m.index)) { seen.add(m.index); labels.push(m) }
  if (labels.length > 1 && labels[1].index - labels[0].index < 3) labels.shift()
  const earlier = [...byDay.values()].filter((a) => a.date < first).reduce((s, a) => s + (Number(a.count) || 0), 0)
  return { weeks: cols, months: labels, max, shown, earlier }
}

/** "3 runs on Tue, 12 Nov 2026" for a calendar cell. */
export function dayLabel(cell, locale = undefined) {
  const [y, m, d] = String(cell?.date || '').split('-').map(Number)
  const when = y ? new Date(y, m - 1, d).toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : ''
  const n = Number(cell?.count) || 0
  return `${n === 0 ? 'No runs' : n === 1 ? '1 run' : `${n} runs`} on ${when}`
}

/** Run names saved on `day`, from the activity list. */
export function namesOnDay(activity, day) {
  const hit = arr(activity).find((a) => a && a.date === day)
  return new Set(arr(hit?.runs))
}

/** Buying-intent rows, newest first, with a shared axis maximum (rounded up to 10, at least 10). */
export function intentRows(intent, limit = Infinity) {
  const rows = arr(intent).filter((r) => r && finite(r.rate) && finite(r.n) && r.n > 0)
    .map((r) => ({ ...r, low: finite(r.low) ? r.low : r.rate, high: finite(r.high) ? r.high : r.rate, small: r.n < 30 }))
  rows.sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')) || String(a.run).localeCompare(String(b.run)))
  const axis = Math.max(10, Math.ceil(Math.max(0, ...rows.map((r) => r.high)) / 10) * 10)
  return { rows: rows.slice(0, limit), axis: Math.min(100, axis), total: rows.length }
}

/** Percent of `axis` for CSS positions, clamped to 0..100. */
export const position = (value, axis) => (finite(value) && axis > 0 ? Math.min(100, Math.max(0, (value / axis) * 100)) : 0)

/** 12.345 -> "12.3%"; whole numbers lose the decimal. */
export const pct = (v) => (finite(v) ? `${Math.round(v * 10) / 10}%` : '—')

/** US dollars for spend estimates: cents under $10, whole dollars above. */
export function usd(v) {
  if (!finite(v)) return '—'
  const digits = Math.abs(v) < 10 ? 2 : 0
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)
}

/** Bar widths for a ranked list: share of the biggest value, at least 2% so a non-zero row stays visible. */
export function barWidths(rows, key) {
  const max = Math.max(0, ...arr(rows).map((r) => (finite(r?.[key]) ? r[key] : 0)))
  return arr(rows).map((r) => (max > 0 && finite(r?.[key]) && r[key] > 0 ? Math.max(2, Math.round((r[key] / max) * 100)) : 0))
}

const GRADE_TEXT = { A: 'firm', B: 'solid direction', C: 'direction only', D: 'sketch' }
/** Grade letter -> short plain words. */
export const gradeText = (g) => GRADE_TEXT[g] || 'not graded'

/** Grade counts A-D in order, with zeros, for the trust strip. */
export function gradeCounts(grades) {
  const g = obj(grades)
  return ['A', 'B', 'C', 'D'].map((letter) => ({ grade: letter, count: Number(g[letter]) || 0 }))
}

/** The one-line nudge shown when no run was checked against real people (null once one was). */
export function trustNudge(trust, totalRuns) {
  const t = obj(trust)
  if (!totalRuns || (Number(t.calibrated) || 0) > 0) return null
  return 'None of these runs has been checked with real people yet. Open a run and use its real-people check to ask a few real buyers the same questions.'
}

const OUTCOME = { hit: 'All checks hit', miss: 'Missed', mixed: 'Partly hit', no_checks: 'Scored, nothing to compare', pending: 'Waiting for real results' }
/** Ledger outcome -> plain words. */
export const outcomeText = (o) => OUTCOME[o] || 'Waiting for real results'

/** Running runs worth polling: not stale. */
export const pollable = (running) => arr(running).filter((r) => r && r.name && !r.stale)

const ACTIVE = /^(running|preparing|processing|pending|queued|in_progress|starting)$/i
/** Whether a /api/runs/<name>/status reply still says the run is busy. */
export function stillRunning(status) {
  const s = obj(status)
  if (s.finished_at || s.error) return false
  return ACTIVE.test(String(obj(s.run).runner_status || ''))
}

/** Plain stage text for a live run from its /status reply (or its insights row when no reply came yet). */
export function liveStage(status, fallback = {}) {
  const s = obj(status), run = obj(s.run), f = obj(fallback)
  const round = finite(run.current_round) ? run.current_round : f.current_round
  const total = finite(run.total_rounds) ? run.total_rounds : f.total_rounds
  const stages = arr(s.stages)
  const next = stages.find((x) => x && !x.done)
  if (finite(total) && total > 0 && finite(round)) return `Social rounds: round ${Math.min(round, total)} of ${total}`
  if (next?.label) return `Working on: ${String(next.label).toLowerCase()}`
  const state = String(run.runner_status || f.status || 'running').replaceAll('_', ' ')
  return state.charAt(0).toUpperCase() + state.slice(1)
}

/** Progress 0-100 from a status reply, else the insights row; null when unknown. */
export function liveProgress(status, fallback = {}) {
  const v = obj(obj(status).run).progress_percent
  const p = finite(v) ? v : obj(fallback).progress_percent
  return finite(p) ? Math.min(100, Math.max(0, p)) : null
}
