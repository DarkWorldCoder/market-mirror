// Pure helpers for the in-chat run card (components/workspace/RunChatCard.vue) and the next-step chips under the
// latest answer. No network and no model calls: everything reads values that are already loaded.
import { decisionText, decisionTone, displayTitle, shortText } from './compareRuns.js'
import { sampleCount } from './charts.js'
import { plural } from './plural.js'

/** The same tabs, ids and order as the run page (RunView.vue), so "Open full page" lands on the matching tab. */
export const RUN_CARD_TABS = [
  { id: 'results', label: 'Results' },
  { id: 'market', label: 'Audience & world' },
  { id: 'thinking', label: 'Buyer responses' },
  { id: 'activity', label: 'Activity' },
  { id: 'feed', label: 'Social feed' }
]

const TAB_ALIASES = {
  results: 'results', reports: 'results', report: 'results', highlights: 'results',
  market: 'market', audience: 'market', world: 'market', world_map: 'market', map: 'market',
  thinking: 'thinking', responses: 'thinking', buyers: 'thinking', survey: 'thinking', buyer_responses: 'thinking',
  activity: 'activity', timeline: 'activity', recorded_activity: 'activity',
  feed: 'feed', social: 'feed', social_feed: 'feed', 'social feed': 'feed'
}

/** A view name from a link, the agent's open_view or an evidence label ("Social feed") -> a card tab id. */
export function tabForView(view) {
  const key = String(view || '').trim().toLowerCase()
  return TAB_ALIASES[key] || TAB_ALIASES[key.replace(/\s+/g, '_')] || 'results'
}

/** WAI-ARIA tabs keyboard model: arrows wrap, Home and End jump. Returns the next tab id, or null for other keys. */
export function moveTab(tabs, current, key) {
  const ids = (tabs || []).map((t) => t.id)
  if (!ids.length) return null
  const i = Math.max(0, ids.indexOf(current))
  if (key === 'ArrowRight') return ids[(i + 1) % ids.length]
  if (key === 'ArrowLeft') return ids[(i - 1 + ids.length) % ids.length]
  if (key === 'Home') return ids[0]
  if (key === 'End') return ids[ids.length - 1]
  return null
}

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const pct = (v) => `${Math.round(v * 10) / 10}%`

/**
 * The card header from GET /api/runs/<name>: verdict and key numbers. Every number is simulated and says so;
 * small samples read as counts ("3 of 28"), as on the run page.
 */
export function runCardStats(detail) {
  const summary = detail?.summary || {}
  const mk = summary.marketing || {}
  const overall = mk.overall || {}
  const decision = summary.decision?.decision || detail?.decision || ''
  const people = num(detail?.people) ?? num(mk.people) ?? num(summary.agents)
  const segments = Array.isArray(mk.by_segment) ? mk.by_segment.filter((s) => s && s.key != null).length : null
  const answered = Number.isInteger(overall.n) ? overall.n : people
  const numbers = []
  if (people != null) numbers.push({ key: 'people', value: Number(people).toLocaleString('en-US'), label: 'people' })
  if (segments) numbers.push({ key: 'segments', value: String(segments), label: plural(segments, { one: 'segment', other: 'segments' }) })
  for (const [key, label] of [['convert_yes', 'would buy'], ['convert_maybe', 'maybe']]) {
    const v = num(overall[key])
    if (v == null) continue
    const small = sampleCount(v, answered)
    numbers.push(small ? { key, value: small.text, label, note: small.pct } : { key, value: pct(v), label })
  }
  return {
    title: detail?.title || summary.project_name || detail?.name || '',
    decision,
    decisionLabel: decision ? decisionText(decision) : '',
    tone: decision ? decisionTone(decision) : '',
    summary: summary.decision?.summary || '',
    numbers
  }
}

/** The file "Download report" saves: the plain-language report first, then the structured ones. */
export function reportDownloadFile(files) {
  const have = new Set(Array.isArray(files) ? files : [])
  return ['market_report.md', 'report.md', 'market_report.json', 'summary.json'].find((f) => have.has(f)) || ''
}

/** The saved report the Results tab reads (it has a plain-language layout in reportPresentation.js). */
export function resultsFile(files) {
  const have = new Set(Array.isArray(files) ? files : [])
  return ['summary.json', 'market_report.json'].find((f) => have.has(f)) || ''
}

export function hasFeed(files) {
  return (Array.isArray(files) ? files : []).some((f) => /^(feed_story|timeline|feed_test)\.json$|^posts_\w+\.json$/.test(f))
}

const VERDICTS = ['yes', 'maybe', 'no']

/** Survey answers as readable rows: who, their verdict and their own words. Rows without words are left out. */
export function buyerResponses(survey, verdict = '') {
  const rows = []
  for (const r of Array.isArray(survey?.responses) ? survey.responses : []) {
    const a = r?.answer || {}
    const v = String(a.would_convert || '').toLowerCase()
    const said = a.quote || a.texts?.purchase || ''
    if (!said && !a.main_objection) continue
    if (verdict && v !== verdict) continue
    rows.push({
      id: String(r.agent_id ?? rows.length),
      who: r.name || `Person ${r.agent_id ?? rows.length + 1}`,
      verdict: VERDICTS.includes(v) ? v : '',
      said,
      objection: a.main_objection || '',
      change: a.would_change_mind || ''
    })
  }
  return rows
}

/** How many answers said yes, maybe and no (from every response, with or without words). */
export function verdictCounts(survey) {
  const out = { yes: 0, maybe: 0, no: 0 }
  for (const r of Array.isArray(survey?.responses) ? survey.responses : []) {
    const v = String(r?.answer?.would_convert || '').toLowerCase()
    if (v in out) out[v]++
  }
  return out
}

/** Recorded actions per round, in round order, with a 0-100 share of the busiest round for the bar width. */
export function activityRounds(timeline) {
  const rows = (Array.isArray(timeline) ? timeline : [])
    .filter((r) => num(r?.round_num) != null && num(r?.total_actions) != null && r.total_actions >= 0)
    .sort((a, b) => a.round_num - b.round_num)
  const max = Math.max(1, ...rows.map((r) => r.total_actions))
  return rows.map((r) => ({ round: r.round_num, total: r.total_actions, active: num(r.active_agents_count), share: Math.round((r.total_actions / max) * 100) }))
}

const ACTION_LABELS = { CREATE_POST: 'posts', CREATE_COMMENT: 'comments', LIKE_POST: 'post likes', LIKE_COMMENT: 'comment likes', DISLIKE_POST: 'dislikes', REPOST: 'reposts', QUOTE_POST: 'quotes', FOLLOW: 'follows', SEARCH_POSTS: 'searches' }

/** The most active people, leaving out "did nothing", with their top actions in words. */
export function topActors(stats, n = 6) {
  const rows = Array.isArray(stats) ? stats : Array.isArray(stats?.agents) ? stats.agents : []
  return rows
    .map((r) => {
      const types = Object.entries(r?.action_types || {}).filter(([k, v]) => k !== 'DO_NOTHING' && num(v) && v > 0)
      const acted = types.reduce((sum, [, v]) => sum + v, 0)
      return { id: String(r?.agent_id ?? ''), who: r?.agent_name || `Person ${r?.agent_id}`, acted, detail: types.sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${v} ${ACTION_LABELS[k] || k.toLowerCase().replaceAll('_', ' ')}`).join(', ') }
    })
    .filter((r) => r.acted > 0)
    .sort((a, b) => b.acted - a.acted)
    .slice(0, n)
}

/** Total actions by type across the run, biggest first, without "did nothing". */
export function actionMix(timeline) {
  const totals = {}
  for (const r of Array.isArray(timeline) ? timeline : []) {
    for (const [k, v] of Object.entries(r?.action_types || {})) if (k !== 'DO_NOTHING' && num(v)) totals[k] = (totals[k] || 0) + v
  }
  return Object.entries(totals).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, label: ACTION_LABELS[k] || k.toLowerCase().replaceAll('_', ' '), count: v }))
}

/** Other saved runs to compare with, newest first (the run index is newest first). */
export function compareChoices(runs, current, limit = 8) {
  return (Array.isArray(runs) ? runs : []).filter((r) => r?.name && r.name !== current).slice(0, limit)
    .map((r) => ({ name: r.name, title: shortText(displayTitle(r.title || r.name), 48), decision: r.decision || '' }))
}

/**
 * Next-step chips for a run shown in the chat. `cost: 'free'` chips are answered from saved files without a model
 * call; `cost: 'approval'` chips go to the chat agent as a message, and the agent asks for approval (with a cost
 * estimate) before any paid step runs. Chips never start paid work themselves.
 */
export function nextStepChips({ run, title = '', runs = [], files = [], summary = null, exclude = [] } = {}, limit = 4) {
  if (!run) return []
  const skip = new Set(exclude)
  const mk = summary?.marketing || {}
  const label = shortText(displayTitle(title || run), 40)
  const chips = []
  if (mk.objections?.length) chips.push({ id: 'why-no', label: 'Why did people say no?', prompt: 'Why did people say no?', query: 'objections', run, cost: 'free', kind: 'local' })
  if (files.includes('config.json')) chips.push({ id: 'map', label: 'Show the world map', prompt: 'Show the world map', run, cost: 'free', kind: 'view', tab: 'market' })
  const other = compareChoices(runs, run, 1)[0]
  if (other) chips.push({ id: 'compare', label: 'Compare with the last run', prompt: `Compare ${label} with ${other.title}`, run, other: other.name, cost: 'free', kind: 'compare' })
  if (mk.pricing || mk.offer) chips.push({ id: 'cheaper', label: 'Test a cheaper price', prompt: `Test a cheaper price for ${label}: plan a rerun of the buyer survey with a lower price, and show me the cost before anything runs.`, run, cost: 'approval', kind: 'agent' })
  if (mk.by_segment?.length > 1) chips.push({ id: 'segments', label: 'Which audience should we target?', prompt: 'Which audience should we target?', query: 'segment', run, cost: 'free', kind: 'local' })
  if (hasFeed(files)) chips.push({ id: 'feed', label: 'Show the social feed', prompt: 'Show the social feed', run, cost: 'free', kind: 'view', tab: 'feed' })
  chips.push({ id: 'follow-up', label: 'Ask the buyers a follow-up', prompt: `Ask the simulated buyers from ${label} a follow-up question, and show me the cost before anything runs.`, run, cost: 'approval', kind: 'agent' })
  // keep one paid idea in view when there is room, so the free ones do not crowd it out
  const fit = chips.filter((c) => !skip.has(c.id))
  const free = fit.filter((c) => c.cost === 'free'), paid = fit.filter((c) => c.cost !== 'free')
  return [...free.slice(0, Math.max(limit - 1, limit - paid.length)), ...paid].slice(0, limit)
}

/** Text for the assistant message that carries a run card. */
export function runCardIntro(tab, title) {
  const name = shortText(displayTitle(title), 60)
  const what = { results: 'the results', market: 'the audience and the world map', thinking: 'what the buyers said', activity: 'the recorded activity', feed: 'the social feed' }[tab] || 'the results'
  return `This is ${what} for **${name}**, read from the saved run with no model call. Use the tabs to look around. Every number comes from simulated buyers.`
}

/** What the user's message says when a saved view opens in the chat (also used to find a chat that shows it). */
export const EVIDENCE_PROMPTS = {
  results: 'Show the results',
  market: 'Show the audience and world map',
  thinking: 'Show what the buyers said',
  activity: 'Show the recorded activity',
  feed: 'Show the social feed'
}
export function evidencePrompt(tab) { return EVIDENCE_PROMPTS[tabForView(tab)] }

/**
 * A typed or chip message about the selected run that the saved files answer without a model call, or null.
 * Kept to near-exact phrases, so ordinary questions still go to the chat agent.
 */
export function localRunIntent(text) {
  const t = String(text || '').trim().toLowerCase().replace(/[?.!]+$/, '')
  if (/^why did (people|buyers|they) (say no|not buy|walk away)$|^(show|what were) the (top )?objections$/.test(t)) return { kind: 'objections', tab: 'thinking', verdict: 'no' }
  if (/^which (audience|segment) should (we|i) target$|^(which|what) (audience|segment) (is|was) (best|strongest)$/.test(t)) return { kind: 'segments', tab: 'market' }
  const view = /^(show|open|view|explore) (me )?(the )?(results|world map|audience( and world map)?|3d world and audience|what the buyers said|buyer responses|(recorded )?activity|social feed|all reports)$/.exec(t)
  if (!view) return null
  const what = view[4]
  const tab = /world|audience/.test(what) ? 'market' : /buyer/.test(what) ? 'thinking' : /activity/.test(what) ? 'activity' : /feed/.test(what) ? 'feed' : 'results'
  return { kind: 'view', tab }
}

const fmtPct = (v) => `${Math.round(v * 10) / 10}%`

/** "Why did people say no?" from summary.json: the saved objections in order, labelled simulated. */
export function objectionAnswer(summary) {
  const rows = (summary?.marketing?.objections || []).filter((o) => o && o.label && num(o.share) != null).slice(0, 4)
  if (!rows.length) return 'This run saved no objections. The answers from each simulated buyer are below.'
  const lines = rows.map((o, i) => `${i + 1}. **${o.label}**: ${fmtPct(o.share)}${num(o.count) != null ? ` (${Number(o.count).toLocaleString('en-US')} people)` : ''}`)
  return ['The main reasons simulated buyers gave for holding back, from the saved run (no model call):', '', ...lines, '', 'Simulated: read the order, not the exact sizes. Their own words are below, filtered to the people who said no.'].join('\n')
}

/** "Which audience should we target?" from summary.json: segments by would-buy, with sizes and a close-call note. */
export function segmentAnswer(summary) {
  const rows = (summary?.marketing?.by_segment || []).filter((s) => s && s.key != null && num(s.convert_yes) != null)
    .sort((a, b) => b.convert_yes - a.convert_yes)
  if (!rows.length) return 'This run saved no audience breakdown, so there is nothing to rank yet.'
  const lines = rows.slice(0, 4).map((s, i) => `${i + 1}. **${s.key}**: ${fmtPct(s.convert_yes)} would buy${Number.isInteger(s.n) ? ` (${s.n.toLocaleString('en-US')} people)` : ''}`)
  const [a, b] = rows
  const close = b && (a.convert_yes - b.convert_yes < 3 || (Number.isInteger(a.n) && a.n < 10))
  const note = close
    ? `Close call: **${a.key}** leads by less than 3 points or has few people, so treat the order as a hint and check it with real people.`
    : `**${a.key}** leads in this simulated run. Gaps between simulated audiences tend to run larger than real ones, so check it with real people before you shift budget.`
  return ['Audiences ranked by simulated would-buy, from the saved run (no model call):', '', ...lines, '', note].join('\n')
}

/** The saved run an assistant message is about (run card, older evidence views, artifacts, agent cards), or ''. */
export function messageRun(m) {
  if (!m || m.role !== 'assistant') return ''
  const card = (m.agent?.cards || []).find((c) => c?.type === 'artifact' && c.run)
  return m.run_card?.run || m.audience_run || m.reportBrowser?.run || (m.artifacts || []).find((a) => a?.run)?.run || card?.run || ''
}

/** Chips not worth offering under a message that already shows the same thing. */
export function shownChips(m) {
  const out = []
  const tab = m?.run_card?.tab
  if (tab === 'market' || m?.audience_run) out.push('map')
  if (tab === 'feed') out.push('feed')
  if (m?.run_card?.verdict === 'no') out.push('why-no')
  if (m?.run_card?.focus === 'segments') out.push('segments')
  return out
}
