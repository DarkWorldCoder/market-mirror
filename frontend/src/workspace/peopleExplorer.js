// Pure helpers for the People explorer (components/workspace/PeopleExplorer.vue): one row per simulated person in a
// saved run, built from config.json persona_index, survey.json answers, agent_stats.json and the thoughts harvest.
// Search, filters, sort, the summary strip, the comparison table and the CSV download. No network, no model calls.

export const VERDICTS = ['yes', 'maybe', 'no', 'none']
export const VERDICT_LABEL = { yes: 'Would buy', maybe: 'Maybe', no: 'Would not buy', none: 'Not asked' }
export const AGE_BANDS = ['Under 25', '25 to 34', '35 to 44', '45 to 54', '55 and over', 'Age not saved']
export const SORTS = [
  { id: 'name', label: 'Name' },
  { id: 'age', label: 'Age' },
  { id: 'active', label: 'Most active' },
  { id: 'answer', label: 'Answer' }
]
export const MAX_COMPARE = 3
export const FACETS = [
  { id: 'segment', label: 'Segment' },
  { id: 'country', label: 'Country' },
  { id: 'verdict', label: 'Would buy' },
  { id: 'gender', label: 'Gender' },
  { id: 'ageBand', label: 'Age' }
]
const OBJECTION_LABEL = {
  trust: 'Trust', price: 'Price', effort: 'Effort', unclear: 'Unclear offer', privacy: 'Privacy', relevance: 'Not relevant to them',
  timing: 'Timing', other: 'Other', none: 'No objection'
}
const UNSPECIFIED = 'Unspecified segment'

const text = (v) => (v === null || v === undefined ? '' : String(v).trim())
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const plain = (s) => cap(text(s).replace(/[-_]+/g, ' '))
const firstSentence = (s) => {
  const t = text(s)
  const m = t.match(/^(.{20,180}?[.!?])(\s|$)/)
  return m ? m[1] : t.slice(0, 180)
}

/** A list saved as an array or as a Python-style string ("['English', 'Hindi']") -> "English, Hindi". */
export function listText(v) {
  if (Array.isArray(v)) return v.map(text).filter(Boolean).join(', ')
  const s = text(v)
  if (s.startsWith('[')) {
    try { return JSON.parse(s.replace(/'/g, '"')).map(text).filter(Boolean).join(', ') } catch { return s.replace(/[[\]']/g, '') }
  }
  return s
}

export function ageNumber(age) {
  const n = Number.parseInt(text(age), 10)
  return Number.isFinite(n) && n > 0 && n < 130 ? n : null
}

export function ageBand(age) {
  const n = ageNumber(age)
  if (n === null) return AGE_BANDS[5]
  if (n < 25) return AGE_BANDS[0]
  if (n < 35) return AGE_BANDS[1]
  if (n < 45) return AGE_BANDS[2]
  if (n < 55) return AGE_BANDS[3]
  return AGE_BANDS[4]
}

export function initials(name) {
  return text(name).split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join('').toUpperCase() || '?'
}

export function verdictKey(v) {
  const k = text(v).toLowerCase()
  return k === 'yes' || k === 'maybe' || k === 'no' ? k : 'none'
}

export function objectionLabel(type) {
  const k = text(type).toLowerCase()
  return OBJECTION_LABEL[k] || plain(k) || ''
}

/** Segment -> colour, in the order segments first appear among people (as the audience card does). */
export function segmentColorMap(index, colors) {
  const out = {}
  const segs = [...new Set((index || []).filter(isPersona).map((p) => text(p.segment) || UNSPECIFIED))]
  segs.forEach((s, i) => { out[s] = colors.length ? colors[i % colors.length] : '#4b5563' })
  return out
}

/** Things a person actually did (posts, comments, likes, follows), leaving out rounds where they did nothing. */
export function activeActions(stat) {
  if (!stat) return 0
  const types = stat.action_types && typeof stat.action_types === 'object' ? Object.entries(stat.action_types) : null
  if (types && types.length) return types.reduce((n, [k, v]) => n + (String(k).toUpperCase() === 'DO_NOTHING' ? 0 : Number(v) || 0), 0)
  return Number.isFinite(Number(stat.total_actions)) ? Number(stat.total_actions) : 0
}

export const isPersona =(p) => p && typeof p === 'object' && (p.kind || 'persona') === 'persona'
const statsList = (stats) => (Array.isArray(stats) ? stats : Array.isArray(stats?.agents) ? stats.agents : [])

/**
 * One row per simulated person (community and brand accounts are left out: they were never asked whether they would buy).
 * `thoughts` is the entries array from GET /api/runs/<name>/thoughts; it only fills the quote when the survey has none.
 */
export function buildPeople({ index = [], survey = null, stats = null, thoughts = [], colors = [] } = {}) {
  const answers = new Map()
  for (const r of survey?.responses || []) {
    if (r && r.agent_id !== undefined && r.agent_id !== null) answers.set(String(r.agent_id), r)
  }
  const acts = new Map(statsList(stats).filter((s) => s && s.agent_id !== undefined).map((s) => [String(s.agent_id), s]))
  const said = new Map()
  for (const t of thoughts || []) {
    const id = t && t.agent_id !== undefined && t.agent_id !== null ? String(t.agent_id) : ''
    if (id && text(t.text) && !said.has(id) && t.source !== 'survey') said.set(id, t)
  }
  const color = segmentColorMap(index, colors)
  const rows = []
  for (const p of index || []) {
    if (!isPersona(p) || p.agent_id === undefined || p.agent_id === null) continue
    const id = String(p.agent_id)
    const response = answers.get(id)
    const answer = response && response.answer && typeof response.answer === 'object' ? response.answer : null
    const stat = acts.get(id) || null
    const verdict = verdictKey(answer?.would_convert)
    const quote = text(answer?.quote)
    const objection = text(answer?.main_objection)
    const thought = said.get(id)
    const segment = text(p.segment)
    const why = quote || objection || text(answer?.texts?.purchase) || text(thought?.text) || firstSentence(p.interview_summary)
    const whySource = quote ? 'In their words' : objection ? 'Holding back' : answer?.texts?.purchase ? 'Their answer' : thought ? 'They wrote' : why ? 'Background' : ''
    const row = {
      id, name: text(p.name) || `Person ${id}`, initials: initials(p.name), age: ageNumber(p.age), ageBand: ageBand(p.age),
      gender: plain(p.gender) || 'Not saved', city: text(p.city), country: text(p.country) || 'Country not saved',
      segment: segment || UNSPECIFIED, color: color[segment || UNSPECIFIED] || '#4b5563',
      occupation: text(p.occupation), income: plain(p.income_level || p.income), education: plain(p.education),
      mediaDiet: text(p.media_diet), platformHabits: text(p.platform_habits), interview: text(p.interview_summary),
      bde: p.bde && typeof p.bde === 'object' ? p.bde : null, weight: Number.isFinite(Number(p.weight)) && p.weight !== null && p.weight !== '' ? Number(p.weight) : null,
      asked: !!answer, verdict, answer, quote, objection, objectionType: text(answer?.objection_type).toLowerCase(),
      changeMind: text(answer?.would_change_mind), why, whySource, thought: thought ? text(thought.text) : '',
      actions: activeActions(stat), stats: stat, person: p
    }
    row.search = [row.name, row.city, row.country, row.occupation, row.segment, quote, objection, row.changeMind, text(answer?.texts?.purchase), row.thought]
      .join(' \n ').toLowerCase()
    rows.push(row)
  }
  return rows
}

/** Chip options per facet with counts over every person, in a stable order. */
export function facetOptions(rows) {
  const out = {}
  for (const f of FACETS) {
    const counts = new Map()
    for (const r of rows) counts.set(r[f.id], (counts.get(r[f.id]) || 0) + 1)
    let values = [...counts.keys()]
    if (f.id === 'verdict') values = VERDICTS.filter((v) => counts.has(v))
    else if (f.id === 'ageBand') values = AGE_BANDS.filter((v) => counts.has(v))
    else values.sort((a, b) => counts.get(b) - counts.get(a) || String(a).localeCompare(String(b)))
    out[f.id] = values.map((value) => ({ value, label: f.id === 'verdict' ? VERDICT_LABEL[value] : value, count: counts.get(value) }))
  }
  return out
}

export const emptyFilters = () => ({ query: '', segment: [], country: [], verdict: [], gender: [], ageBand: [] })

export function activeFilterCount(filters) {
  return (text(filters?.query) ? 1 : 0) + FACETS.reduce((n, f) => n + ((filters?.[f.id] || []).length ? 1 : 0), 0)
}

/** Every search word must appear (name, city, occupation or their words). Chips: any value in a group, all groups. */
export function filterPeople(rows, filters = {}) {
  const words = text(filters.query).toLowerCase().split(/\s+/).filter(Boolean)
  const sets = FACETS.map((f) => [f.id, new Set(filters[f.id] || [])]).filter(([, s]) => s.size)
  return rows.filter((r) => sets.every(([k, s]) => s.has(r[k])) && words.every((w) => r.search.includes(w)))
}

export function toggleValue(list, value) {
  const arr = Array.isArray(list) ? list : []
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value]
}

const ORDER = { yes: 0, maybe: 1, no: 2, none: 3 }
const byName = (a, b) => a.name.localeCompare(b.name) || Number(a.id) - Number(b.id) || a.id.localeCompare(b.id)

export function sortPeople(rows, key = 'name') {
  const out = [...rows]
  if (key === 'age') out.sort((a, b) => (a.age ?? Infinity) - (b.age ?? Infinity) || byName(a, b))
  else if (key === 'active') out.sort((a, b) => b.actions - a.actions || byName(a, b))
  else if (key === 'answer') out.sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict] || byName(a, b))
  else out.sort(byName)
  return out
}

const pct = (n, d) => (d ? Math.round((n / d) * 1000) / 10 : 0)
const fmt = (n) => Number(n).toLocaleString('en-US')

/** The strip above the grid, for the people currently shown. Every number is simulated. */
export function peopleSummary(rows) {
  const asked = rows.filter((r) => r.asked)
  const count = (v) => asked.filter((r) => r.verdict === v).length
  const yes = count('yes'), maybe = count('maybe'), no = count('no')
  const objections = new Map()
  for (const r of asked) {
    if (!r.objectionType || r.objectionType === 'none') continue
    const o = objections.get(r.objectionType) || { type: r.objectionType, label: objectionLabel(r.objectionType), count: 0, example: '' }
    o.count++
    if (!o.example && r.objection) o.example = r.objection
    objections.set(r.objectionType, o)
  }
  const top = [...objections.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))[0] || null
  const jobs = new Map()
  for (const r of rows) {
    if (!r.occupation) continue
    const key = r.occupation.toLowerCase()
    const j = jobs.get(key) || { label: r.occupation, count: 0 }
    j.count++
    jobs.set(key, j)
  }
  const topJobs = [...jobs.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)).slice(0, 3)
  return {
    people: rows.length, asked: asked.length, yes, maybe, no,
    yesPct: pct(yes, asked.length), maybePct: pct(maybe, asked.length),
    buyText: asked.length ? `${fmt(yes)} of ${fmt(asked.length)} asked (${pct(yes, asked.length)}%)` : 'Nobody here was asked',
    topObjection: top ? { ...top, pct: pct(top.count, asked.length) } : null,
    topOccupations: topJobs
  }
}

/** Selected ids for the comparison: at most three, a second tick removes. */
export function toggleCompare(ids, id, max = MAX_COMPARE) {
  const list = Array.isArray(ids) ? ids.map(String) : []
  const key = String(id)
  if (list.includes(key)) return list.filter((x) => x !== key)
  return list.length >= max ? list : [...list, key]
}

/** "Considered, cautious. Stops at: hidden auto-renewal" from the decision card (background / decision / evaluation). */
export function decisionCard(bde) {
  if (!bde || typeof bde !== 'object') return []
  const d = bde.decision_procedure || {}, e = bde.evaluation || {}, b = bde.background || {}
  const out = []
  const how = [text(d.speed), text(d.risk) && `${text(d.risk)} on risk`, text(d.style)].filter(Boolean).join(', ')
  if (how) out.push({ label: 'How they decide', value: cap(how) })
  if (text(d.who_they_ask)) out.push({ label: 'Who they ask', value: text(d.who_they_ask) })
  const stops = [...new Set([...(Array.isArray(d.stoppers) ? d.stoppers : []), ...(Array.isArray(e.dealbreakers) ? e.dealbreakers : [])].map(text).filter(Boolean))]
  if (stops.length) out.push({ label: 'What stops them', value: stops.join(', ') })
  if (Array.isArray(d.triggers) && d.triggers.length) out.push({ label: 'What moves them', value: d.triggers.map(text).filter(Boolean).join(', ') })
  if (text(e.monthly_discretionary)) out.push({ label: 'Spare money a month', value: text(e.monthly_discretionary) })
  if (text(b.says_vs_does)) out.push({ label: 'Says versus does', value: text(b.says_vs_does) })
  if (text(b.knows)) out.push({ label: 'What they know', value: text(b.knows) })
  return out
}

/** Side-by-side rows for up to three people: label plus one value per person ('' when not saved). */
export function compareRows(people) {
  const list = people || []
  const where = (r) => [r.city, r.country].filter(Boolean).join(', ')
  const fields = [
    ['Segment', (r) => r.segment], ['Age', (r) => (r.age ? String(r.age) : '')], ['Gender', (r) => r.gender], ['Lives in', where],
    ['Job', (r) => r.occupation], ['Income', (r) => (r.income ? `${r.income} income` : '')], ['Education', (r) => r.education],
    ['Media', (r) => r.mediaDiet], ['Would buy (simulated)', (r) => VERDICT_LABEL[r.verdict]],
    ['Main objection', (r) => [r.objectionType && objectionLabel(r.objectionType), r.objection].filter(Boolean).join(': ')],
    ['Would change their mind', (r) => r.changeMind],
    ['What they did', (r) => activityText(r.stats)],
    ['How they decide', (r) => decisionCard(r.bde).find((x) => x.label === 'How they decide')?.value || ''],
    ['A quote', (r) => r.quote || r.thought]
  ]
  return fields.map(([label, get]) => ({ label, values: list.map((r) => text(get(r))) })).filter((row) => row.values.some(Boolean))
}

const ACTION_WORDS = {
  CREATE_POST: ['wrote', 'post'], CREATE_COMMENT: ['wrote', 'comment'], QUOTE_POST: ['quoted', 'post'], REPOST: ['shared', 'post'],
  LIKE_POST: ['liked', 'post'], LIKE_COMMENT: ['liked', 'comment'], DISLIKE_POST: ['disliked', 'post'], DISLIKE_COMMENT: ['disliked', 'comment'],
  FOLLOW: ['followed', 'person', 'people'], SEARCH_POSTS: ['searched', 'time']
}
/** "Wrote 2 posts and liked 1 comment" from agent_stats.json, or a plain note when nothing was recorded. */
export function activityText(stats) {
  if (!stats) return 'No social activity recorded'
  const parts = []
  for (const [type, n] of Object.entries(stats.action_types || {})) {
    const w = ACTION_WORDS[String(type).toUpperCase()]
    if (w && n) parts.push(`${w[0]} ${n} ${n === 1 ? w[1] : w[2] || `${w[1]}s`}`)
  }
  if (!parts.length) return stats.total_actions ? `${stats.total_actions} recorded actions, none of them posts or likes` : 'Read the feeds without posting or liking'
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0]
  return cap(list)
}

export const CSV_COLUMNS = [
  ['agent_id', (r) => r.id], ['name', (r) => r.name], ['age', (r) => r.age ?? ''], ['gender', (r) => r.gender], ['city', (r) => r.city],
  ['country', (r) => r.country], ['segment', (r) => r.segment], ['occupation', (r) => r.occupation], ['income_level', (r) => r.income],
  ['education', (r) => r.education], ['media_diet', (r) => r.mediaDiet], ['weight', (r) => r.weight ?? ''],
  ['would_buy', (r) => (r.asked ? r.verdict : 'not asked')], ['objection_type', (r) => r.objectionType], ['main_objection', (r) => r.objection],
  ['would_change_mind', (r) => r.changeMind], ['quote', (r) => r.quote], ['recorded_actions', (r) => r.actions], ['simulated', () => 'yes']
]

/** One CSV cell: quoted when needed, and a leading = + - @ is defused so spreadsheets do not run it as a formula. */
export function csvCell(value) {
  let s = value === null || value === undefined ? '' : String(value)
  if (/^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s)) s = `'${s}`
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** The filtered people as CSV. No contact details: phone, data plan and anything like an email are never exported. */
export function peopleCsv(rows) {
  const lines = [CSV_COLUMNS.map(([k]) => k).join(',')]
  for (const r of rows) lines.push(CSV_COLUMNS.map(([, get]) => csvCell(stripContacts(get(r)))).join(','))
  return `${lines.join('\r\n')}\r\n`
}

/** Removes email addresses and phone-number-looking runs from free text (the people are invented, but exports stay clean). */
export function stripContacts(value) {
  if (typeof value !== 'string') return value
  return value
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '[email removed]')
    .replace(/(?<![\w])\+?\d[\d\s().-]{7,}\d(?![\w])/g, '[number removed]')
}

export function csvFileName(run, filtered) {
  const safe = String(run || 'run').replace(/[^\w.-]+/g, '_').slice(0, 60)
  return `${safe}_people${filtered ? '_filtered' : ''}_simulated.csv`
}
