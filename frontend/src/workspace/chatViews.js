// Everything from the chat: every view the app has, shown inline in the conversation. Pure helpers, no network and
// no model calls: the view list (the same names as the chat agent's open_view), the local parser that answers common
// free requests without a model, and the slash commands' "/people Kenya" arguments.
import { displayTitle, shortText } from './compareRuns.js'

/** Every view, with where it renders: a tab of the run card, the embedded comparison, or a workspace card. */
export const CHAT_VIEWS = {
  results: { kind: 'run', tab: 'results', label: 'Results' },
  reports: { kind: 'run', tab: 'results', label: 'Results' },
  audience: { kind: 'run', tab: 'market', label: 'Audience & world' },
  world_map: { kind: 'run', tab: 'market', label: 'World map' },
  people: { kind: 'run', tab: 'people', label: 'People' },
  buyer_responses: { kind: 'run', tab: 'thinking', label: 'Buyer responses' },
  activity: { kind: 'run', tab: 'activity', label: 'Activity' },
  social_feed: { kind: 'run', tab: 'feed', label: 'Social feed' },
  landing: { kind: 'run', tab: 'landing', label: 'Landing page' },
  brain_response: { kind: 'run', tab: 'brain', label: 'Brain response' },
  compare: { kind: 'compare', label: 'Compare runs' },
  dashboard_map: { kind: 'workspace', label: 'Audience map across runs', simulated: true },
  insights: { kind: 'workspace', label: 'Dashboard insights', simulated: true },
  projects: { kind: 'workspace', label: 'Projects' },
  skills: { kind: 'workspace', label: 'Skills' },
  connectors: { kind: 'workspace', label: 'Connectors' },
  settings_summary: { kind: 'workspace', label: 'Settings' },
  spend: { kind: 'workspace', label: 'Model spend' }
}
export const INSIGHT_PANELS = {
  activity_calendar: 'Activity calendar',
  intent: 'Intent across runs',
  objections: 'Objections across runs',
  audiences: 'Audiences across runs',
  trust: 'Trust and forecasts',
  spend: 'Model spend',
  live_runs: 'Live runs'
}
const FILTER_KEYS = {
  people: ['segment', 'country', 'verdict', 'gender', 'query'],
  buyer_responses: ['verdict', 'segment', 'objection', 'source', 'query']
}
const VERDICTS = ['yes', 'maybe', 'no']
const OBJECTIONS = ['trust', 'price', 'effort', 'unclear', 'privacy', 'relevance', 'timing', 'other']

/** A view spec ({ view, run, runs, panel, filters }) kept to what the view takes, or null for an unknown view. */
export function viewSpec(value = {}) {
  const view = String(value?.view || '').trim()
  const info = CHAT_VIEWS[view]
  if (!info) return null
  const out = { view }
  if (info.kind === 'run' && value.run) out.run = String(value.run)
  if (info.kind === 'compare' && Array.isArray(value.runs) && value.runs.length === 2) out.runs = value.runs.map(String)
  if (view === 'insights' && INSIGHT_PANELS[value.panel]) out.panel = value.panel
  const keys = FILTER_KEYS[view]
  if (keys && value.filters && typeof value.filters === 'object') {
    const f = {}
    for (const k of keys) {
      const v = String(value.filters[k] ?? '').trim().slice(0, 80)
      if (!v) continue
      if (k === 'verdict' && !VERDICTS.includes(v.toLowerCase())) continue
      if (k === 'objection' && !OBJECTIONS.includes(v.toLowerCase())) continue
      f[k] = ['verdict', 'objection', 'source'].includes(k) ? v.toLowerCase() : v
    }
    if (Object.keys(f).length) out.filters = f
  }
  return out
}

/** The run card tab a view opens on (run views only). */
export function viewTab(view) { return CHAT_VIEWS[view]?.tab || 'results' }

/** Plain words for the filters a view opened with ("in Kenya, said no"). */
export function filterWords(filters = {}) {
  const f = filters || {}
  const words = []
  if (f.country) words.push(`in ${f.country}`)
  if (f.segment) words.push(`in the ${f.segment} segment`)
  if (f.verdict) words.push({ yes: 'who would buy', maybe: 'who said maybe', no: 'who said no' }[f.verdict])
  if (f.objection) words.push(`held back by ${f.objection === 'relevance' ? 'relevance' : f.objection}`)
  if (f.gender) words.push(`(${f.gender})`)
  if (f.source) words.push(`from the ${f.source}`)
  if (f.query) words.push(`matching “${f.query}”`)
  return words.filter(Boolean).join(', ')
}

/** The assistant text above a view opened in the chat. Run views name the run; everything says it was free. */
export function viewIntro(spec, title = '') {
  const info = CHAT_VIEWS[spec?.view]
  if (!info) return ''
  const name = title ? `**${shortText(displayTitle(title), 60)}**` : 'this run'
  const filters = filterWords(spec.filters)
  const sim = 'Every number comes from simulated buyers.'
  switch (spec.view) {
    case 'people': return `The simulated people in ${name}${filters ? ` ${filters}` : ''}, read from the saved run with no model call. Change the filters below to look around. ${sim}`
    case 'buyer_responses': return `Answers from the buyers in ${name}${filters ? ` ${filters}` : ''}, read from the saved run with no model call. Each answer was written by a model playing an invented person.`
    case 'activity': return `What happened during ${name}, round by round, read from the saved run with no model call. ${sim}`
    case 'social_feed': return `The simulated social feed of ${name}, read from the saved run with no model call.`
    case 'landing': return `The landing page analysis for ${name}, read from the saved run with no model call. Testing a fix asks first.`
    case 'brain_response': return `The predicted brain response for ${name} (research model, shown beside the simulated buyers, never given to them). No model call.`
    case 'audience': case 'world_map': return `The audience and world map for ${name}, read from the saved run with no model call. ${sim}`
    case 'results': case 'reports': return `The results for ${name}, read from the saved run with no model call. Use the tabs to look around. ${sim}`
    case 'dashboard_map': return 'Where the simulated audiences of all your saved runs live, from saved files with no model call. People are invented; places are where they were set.'
    case 'insights': return spec.panel ? `${INSIGHT_PANELS[spec.panel]}, from your saved runs with no model call.` : 'The dashboard, here in the chat: what your saved runs add up to, read with no model call. Simulated numbers are directions, not measurements.'
    case 'projects': return 'Your projects. Opening one starts a chat with its context; nothing is sent until you write.'
    case 'skills': return 'Everything you can do from this chat. Free ones answer from saved files; the others ask before anything spends.'
    case 'connectors': return 'Which connectors and models are set up, read from this computer with no model call. Manage them on the full page.'
    case 'settings_summary': return 'Your model and workspace settings at a glance, read with no model call. Change them in Settings.'
    case 'spend': return 'What model calls have cost so far, an estimate at list prices, not a bill. Read with no model call.'
    case 'compare': return 'Two saved runs side by side, read with no model call.'
    default: return ''
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Local intents: common free requests answered from saved files with no model connected. Kept to near-exact phrasing
// so ordinary questions still go to the chat agent.
// ---------------------------------------------------------------------------------------------------------------

const clean = (text) => String(text || '').trim().toLowerCase()
  .replace(/[’']/g, "'")
  .replace(/[?.!]+$/, '')
  .replace(/^(please|hey|ok|okay)[,\s]+/, '')
  .replace(/^(can|could|would) you( please)? /, '')
  .replace(/^(i want to|i'd like to|let me|let's) (see|look at|view|open|explore) /, 'show ')
  .replace(/\s+please$/, '')
  .replace(/\s+/g, ' ')
  .trim()

const SHOW = '(?:show|open|view|see|explore|list|display|bring up|pull up|take me to)(?: me)?(?: all)?(?: the| my)?'
const VERDICT_WORDS = [
  [/\b(said|answered|voted)? ?no\b|would ?n[o']t buy|wouldn't buy|won't buy|not buy|walked away|rejected/, 'no'],
  [/\b(said|answered)? ?maybe\b|unsure|on the fence|undecided/, 'maybe'],
  [/\b(said|answered)? ?yes\b|would buy|will buy|bought|want(ed)? to buy/, 'yes']
]
const OBJECTION_WORDS = [
  [/price|cost|expensive|too much money|afford/, 'price'], [/trust|scam|believe/, 'trust'], [/effort|hassle|too hard|work/, 'effort'],
  [/unclear|confus|didn't understand|did not understand/, 'unclear'], [/privacy|data/, 'privacy'],
  [/relevan|not for them|not for me/, 'relevance'], [/timing|not now|later/, 'timing']
]
const verdictIn = (s) => VERDICT_WORDS.find(([re]) => re.test(s))?.[1] || ''
const objectionIn = (s) => OBJECTION_WORDS.find(([re]) => re.test(s))?.[1] || ''

/** The saved run a phrase names (by title or folder name), or ''. Longest match wins. */
export function runNamed(phrase, runs = [], { exact = false } = {}) {
  const p = clean(phrase).replace(/^(the|my) /, '').replace(/ (run|experiment|test)$/, '').trim()
  if (p.length < 3) return ''
  const hits = (runs || []).filter((r) => {
    const title = clean(displayTitle(r.title || '')), name = clean(String(r.name || '').replace(/[_-]+/g, ' '))
    if (exact) return p === title || p === name || p === clean(r.name)
    return (title && (title === p || title.includes(p))) || (name && (name === p || name.includes(p)))
  })
  return hits.sort((a, b) => String(a.title || a.name).length - String(b.title || b.name).length)[0]?.name || ''
}

const SIMPLE = [
  // money and settings: no run needed
  [new RegExp(`^(?:what'?s|what is|how much is|${SHOW}|check)(?: my| the)? (?:model )?(?:spend|spending|spend so far|spend cap|spending cap|spending limit|spend limit)(?: so far)?$`), { view: 'spend' }],
  [/^how much (?:have|did|has) (?:i|we|it|everything) (?:spent|spend|cost)(?: so far)?$/, { view: 'spend' }],
  [/^(?:which|what) connectors? (?:are|is) (?:on|enabled|connected|active|set up|configured|turned on)$/, { view: 'connectors' }],
  [new RegExp(`^(?:${SHOW}|check)(?: my| the)? (?:connectors|connector status|connections|connected (?:tools|accounts|data))(?: status)?$`), { view: 'connectors' }],
  [/^(?:which|what) model (?:am i|are we|is (?:this|the chat)) (?:using|on|set to)$/, { view: 'settings_summary' }],
  [new RegExp(`^(?:${SHOW}|check)(?: my| the)? (?:settings|model settings|settings summary|workspace settings)$`), { view: 'settings_summary' }],
  [new RegExp(`^${SHOW}(?: my| the| all)? projects$`), { view: 'projects' }],
  [new RegExp(`^${SHOW}(?: my| the| all)?(?: available)? (?:skills|tools|commands)$`), { view: 'skills' }],
  [/^what (?:skills|tools|commands) (?:are there|do (?:i|you) have|can i use)$/, { view: 'skills' }],
  [new RegExp(`^${SHOW}(?: my| the)? (?:dashboard(?: world)? map|world map (?:of|across|for) (?:all|every) (?:my )?(?:runs|experiments|audiences)|audience map(?: across runs)?|map of (?:all )?my audiences)$`), { view: 'dashboard_map' }],
  [/^where (?:are|do) (?:all )?my (?:audiences|buyers|simulated people|people) (?:live|come from|from)$/, { view: 'dashboard_map' }],
  [new RegExp(`^${SHOW}(?: my| the)? (?:dashboard|insights|dashboard insights|workspace insights|cross-run insights)$`), { view: 'insights' }],
  [new RegExp(`^${SHOW}(?: my| the)? activity calendar$`), { view: 'insights', panel: 'activity_calendar' }],
  [new RegExp(`^${SHOW}(?: my| the)? (?:purchase )?intent across (?:all )?(?:my )?(?:runs|experiments)$`), { view: 'insights', panel: 'intent' }],
  [new RegExp(`^${SHOW}(?: my| the)? objections across (?:all )?(?:my )?(?:runs|experiments)$`), { view: 'insights', panel: 'objections' }],
  [new RegExp(`^${SHOW}(?: my| the)? audiences across (?:all )?(?:my )?(?:runs|experiments)$`), { view: 'insights', panel: 'audiences' }],
  [new RegExp(`^${SHOW}(?: my| the)? (?:trust(?: and forecasts)?|forecasts|forecast ledger)$`), { view: 'insights', panel: 'trust' }],
  [/^(?:show(?: me)?(?: the| my)? live runs|what'?s running(?: now)?|what is running(?: now)?|is anything running)$/, { view: 'insights', panel: 'live_runs' }]
]

// "show <what> [qualifier]" about one saved run
const RUN_WHAT = [
  ['buyer_responses', /^(?:buyer responses|responses|buyer answers|answers|survey answers|what (?:the )?buyers said|what people said)\b/],
  ['people', /^(?:simulated people|people|persons|personas|buyers|everyone)\b/],
  ['activity', /^(?:recorded activity|activity|timeline|round by round)\b/],
  ['social_feed', /^(?:social feed|feed|social posts|posts)\b/],
  ['landing', /^(?:landing page analysis|landing analysis|landing page teardown|landing teardown|landing page|landing)\b/],
  ['brain_response', /^(?:predicted brain response|brain responses?|brain)\b/],
  ['audience', /^(?:world map|audience map|audience and world map|audience|map)\b/],
  ['results', /^(?:results|report|run results)\b/]
]

/**
 * A free request the saved files answer without a model, as a view spec, or null. `runs` is the run index (newest
 * first); `run` the selected run. Run views fall back to the selected run, then the newest one; `needsRun` marks a
 * run view asked for while no run is saved.
 */
export function localViewIntent(text, { runs = [], run = '' } = {}) {
  const t = clean(text)
  if (!t || t.length > 160 || t.includes('\n')) return null
  for (const [re, spec] of SIMPLE) if (re.test(t)) return { ...spec }
  const m = new RegExp(`^${SHOW} (.+)$`).exec(t) || /^(?:who) (said (?:no|yes|maybe)|would (?:not )?buy|walked away)$/.exec(t)
  if (!m) return null
  let rest = m[1]
  if (/^said |^would |^walked/.test(rest)) rest = `buyer responses that ${rest}`
  const hit = RUN_WHAT.find(([, re]) => re.test(rest))
  if (!hit) return null
  const view = hit[0]
  // "the people in kenya for fitloop v2" / "people of fitloop v2": a trailing run name
  const { qualifier, runName } = trailingRun(rest.replace(hit[1], '').trim(), runs)
  const filters = {}
  if (view === 'people' || view === 'buyer_responses') {
    const q = qualifier.replace(/^(?:that|who|which|where|with)\s+/, '')
    const verdict = /\b(said|answered|would|wouldn't|won't|not buy|walked|rejected|voted|yes|no|maybe|unsure|on the fence)\b/.test(q) ? verdictIn(q) : ''
    if (verdict) filters.verdict = verdict
    if (view === 'buyer_responses') {
      const objection = /\b(about|because of|over|objected|objecting|held back|worried|concerned|complain)\b/.test(q) ? objectionIn(q) : ''
      if (objection) filters.objection = objection
    }
    const seg = /\b(?:in|from) the (.+?) (?:segment|audience|group)\b/.exec(q) || /^(?:in )?(?:the )?(.+?) (?:segment|audience|group)$/.exec(q)
    const place = /\b(?:in|from|living in|based in|who live in) ((?!the )[a-z][a-z .'-]{1,40})$/.exec(q)
    if (seg) filters.segment = titleCase(seg[1])
    else if (place && !VERDICT_WORDS.some(([re]) => re.test(place[1]))) filters[view === 'people' ? 'country' : 'query'] = titleCase(place[1])
    const leftover = q.replace(/^(?:(?:that|who) )?(?:said|answered|would|wouldn't|won't|voted)\b.*$/, '').trim()
    if (!verdict && !filters.objection && !seg && !place && leftover) return null      // something we do not understand
  } else if (qualifier && !/^(?:page|analysis|of (?:this|the|that) run|for (?:this|the|that) run|again)$/.test(qualifier)) {
    return null
  }
  const target = runName || run || runs?.[0]?.name || ''
  return { ...viewSpec({ view, run: target, filters }), ...(target ? {} : { needsRun: true }) }
}

/**
 * Split "in kenya for fitloop v2" into the qualifier and the saved run it ends with. Only "for/of <run>" and
 * "in/from the run <run>" name a run, so "people in Kenya" stays a place even when a run title mentions Kenya.
 */
function trailingRun(qualifier, runs) {
  const lead = /(?:^|\s)(?:for |of |(?:in|from) (?:the )?(?:run|experiment) )/g
  const cuts = [...qualifier.matchAll(lead)].map((x) => x.index).reverse()
  for (const at of cuts) {
    const after = qualifier.slice(at).replace(/^\s*(?:for|of|in|from) (?:the )?(?:run |experiment )?/, '')
    const named = runNamed(after, runs)
    if (named) return { qualifier: qualifier.slice(0, at).trim(), runName: named }
  }
  return { qualifier, runName: '' }
}

function titleCase(s) {
  return String(s || '').trim().replace(/\b([a-z])/g, (c) => c.toUpperCase())
}

// ---------------------------------------------------------------------------------------------------------------
// Slash commands with words after them: "/people kenya", "/responses no", "/insights objections".
// ---------------------------------------------------------------------------------------------------------------

/** { command, rest } for a typed "/command words", or null. */
export function splitSlash(text) {
  const m = /^\/([a-z][a-z0-9-]*)(?:\s+(.*))?$/is.exec(String(text || '').trim())
  return m ? { command: `/${m[1].toLowerCase()}`, rest: (m[2] || '').trim() } : null
}

/** The view a slash command opens with the words after it as filters ("/people kenya" -> people in Kenya). */
export function slashView(view, rest = '', { runs = [], run = '' } = {}) {
  const words = clean(rest)
  // "/people for fitloop v2" or the exact run name picks a run; other words are filters
  const named = !words ? '' : /^for /.test(words) ? runNamed(words.slice(4), runs) : runNamed(words, runs, { exact: true })
  const target = named || run || runs?.[0]?.name || ''
  const base = { view }
  if (CHAT_VIEWS[view]?.kind === 'run') base.run = target
  if (!words || named) return { ...viewSpec(base), ...(CHAT_VIEWS[view]?.kind === 'run' && !target ? { needsRun: true } : {}) }
  if (view === 'people') {
    const verdict = /^(yes|no|maybe)$/.test(words) ? words : ''
    base.filters = verdict ? { verdict } : { country: titleCase(words) }
  } else if (view === 'buyer_responses') {
    const verdict = /^(yes|no|maybe)$/.test(words) ? words : ''
    const objection = OBJECTIONS.includes(words) ? words : ''
    base.filters = verdict ? { verdict } : objection ? { objection } : { query: words }
  } else if (view === 'insights') {
    const panel = Object.keys(INSIGHT_PANELS).find((k) => k === words.replace(/\s+/g, '_') || INSIGHT_PANELS[k].toLowerCase().includes(words) || k.startsWith(words.replace(/\s+/g, '_')))
    if (panel) base.panel = panel
  }
  return { ...viewSpec(base), ...(CHAT_VIEWS[view]?.kind === 'run' && !target ? { needsRun: true } : {}) }
}
