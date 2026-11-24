// What the simulated buyers said, read from a saved run's files with no model call: survey answers (with their
// verdict, objection and what would change their mind), thoughts while scrolling the feed, and the thought stream.
// Pure helpers so the Buyer responses tab can filter, count and page them.

const VERDICTS = ['yes', 'maybe', 'no']
const norm = (v) => String(v ?? '').trim().toLowerCase()
export const verdictOf = (v) => (VERDICTS.includes(norm(v)) ? norm(v) : '')

/** One row per thing a person said or thought. */
export function buildResponses({ survey, feed, stream, index } = {}) {
  const byId = new Map((index || []).map((p) => [String(p.agent_id), p]))
  const person = (id, name) => {
    const p = byId.get(String(id)) || {}
    return { agentId: id === undefined || id === null ? '' : String(id), name: name || p.name || (id !== undefined ? `Person ${id}` : 'Someone'), segment: p.segment || '', country: p.country || '', city: p.city || '' }
  }
  const rows = []
  for (const r of survey?.responses || []) {
    const a = r?.answer
    if (!a || typeof a !== 'object') continue
    const text = a.quote || a.main_objection
    if (!text) continue
    rows.push({
      ...person(r.agent_id, r.name), source: 'survey', verdict: verdictOf(a.would_convert), text: String(text),
      objection: a.quote && a.main_objection && a.main_objection !== a.quote ? String(a.main_objection) : '',
      objectionType: norm(a.objection_type), change: a.would_change_mind ? String(a.would_change_mind) : '',
      interest: Number.isFinite(+a.interest) ? +a.interest : null, trust: Number.isFinite(+a.trust) ? +a.trust : null
    })
  }
  for (const s of feed?.sessions || []) {
    const t = s?.ad?.thought
    if (!t) continue
    rows.push({ ...person(s.agent_id, s.name), source: 'feed', verdict: '', text: String(t), detail: [s.platform, s.creative_id].filter(Boolean).join(' · '), clicked: !!s.ad?.click })
  }
  const items = Array.isArray(stream) ? stream : stream?.thoughts || stream?.items || []
  for (const t of items) {
    const text = t?.text || t?.thought
    if (text) rows.push({ ...person(t.agent_id, t.name), source: 'thought', verdict: '', text: String(text), detail: t.source || '' })
  }
  return rows.map((r, i) => ({ id: `r${i}`, ...r }))
}

/** Filter by verdict, source, objection type, segment and free text (name, place, words). */
export function filterResponses(rows, { verdict = '', source = '', objection = '', segment = '', q = '' } = {}) {
  const words = norm(q).split(/\s+/).filter(Boolean)
  return rows.filter((r) => {
    if (verdict && (verdict === 'none' ? r.verdict : r.verdict !== verdict)) return false
    if (source && r.source !== source) return false
    if (objection && r.objectionType !== objection) return false
    if (segment && r.segment !== segment) return false
    if (words.length) {
      const hay = norm([r.name, r.segment, r.country, r.city, r.text, r.objection, r.change].join(' '))
      if (!words.every((w) => hay.includes(w))) return false
    }
    return true
  })
}

/** Counts for the summary strip: survey verdicts, sources, objection types (largest first), segments. */
export function summarizeResponses(rows) {
  const verdicts = { yes: 0, maybe: 0, no: 0 }
  const sources = {}
  const objections = {}
  const segments = {}
  for (const r of rows) {
    sources[r.source] = (sources[r.source] || 0) + 1
    if (r.source === 'survey') {
      if (r.verdict) verdicts[r.verdict]++
      if (r.objectionType) objections[r.objectionType] = (objections[r.objectionType] || 0) + 1
    }
    if (r.segment) segments[r.segment] = (segments[r.segment] || 0) + 1
  }
  const asked = verdicts.yes + verdicts.maybe + verdicts.no
  const sorted = (o) => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([key, n]) => ({ key, n }))
  return { total: rows.length, asked, verdicts, sources, objections: sorted(objections), segments: sorted(segments) }
}

/** "trust" -> "Trust", "price_value" -> "Price value". */
export const plainLabel = (key) => { const s = String(key || '').replace(/[_-]+/g, ' ').trim(); return s ? s[0].toUpperCase() + s.slice(1) : '' }

/** Per-round action counts by plain kind, for a stacked chart. DO_NOTHING is kept apart as "Only read". */
export function actionsByRound(timeline) {
  const kinds = { posted: ['CREATE_POST'], commented: ['CREATE_COMMENT'], liked: ['LIKE_POST', 'LIKE_COMMENT'], disliked: ['DISLIKE_POST', 'DISLIKE_COMMENT'], shared: ['REPOST', 'QUOTE_POST'], followed: ['FOLLOW'], 'only read': ['DO_NOTHING'] }
  const rounds = (Array.isArray(timeline) ? timeline : []).filter((r) => r && r.action_types)
  const series = {}
  for (const k of Object.keys(kinds)) series[k] = rounds.map((r) => kinds[k].reduce((n, t) => n + (+r.action_types[t] || 0), 0))
  for (const k of Object.keys(series)) if (!series[k].some(Boolean)) delete series[k]
  return { rounds: rounds.map((r, i) => r.round_num ?? r.round ?? i), series, active: rounds.map((r) => (r.active_agents || []).length || r.active_agents_count || 0) }
}
