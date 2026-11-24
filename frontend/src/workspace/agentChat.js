// The chat agent's browser side: the SSE client for /api/workspace/agent/stream and the pure helpers its cards use.
// Approval is decided on the server from each tool's cost class; these helpers only render what the server sent.
import { ensureSession, token } from './api.js'

export const AGENT_EVENTS = ['plan', 'tool_start', 'tool_progress', 'approval_request', 'tool_result', 'artifact', 'error', 'done']
const MAX_FRAME = 512 * 1024
const encoder = new TextEncoder()
const fail = (message, extra = {}) => Object.assign(new Error(message), extra)

/** Read an agent event stream until `done` (returned) or `error` (thrown with status, code and actions). */
export async function consumeAgentStream(response, { signal, onEvent, maxFrameBytes = MAX_FRAME } = {}) {
  if (!response.body) throw fail('The response stream is unavailable. Refresh and try again.')
  const reader = response.body.getReader(), decoder = new TextDecoder('utf-8')
  let buffer = '', name = 'message', data = [], bytes = 0, done = null
  const abort = () => { reader.cancel(signal?.reason).catch(() => {}) }
  signal?.addEventListener('abort', abort, { once: true })
  function dispatch() {
    if (data.length && AGENT_EVENTS.includes(name)) {
      let value
      try { value = JSON.parse(data.join('\n')) } catch { throw fail('The response contained invalid stream data.') }
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw fail('The response contained an invalid stream event.')
      onEvent?.(name, value)
      if (name === 'error') throw fail(typeof value.message === 'string' ? value.message : 'Could not complete this response.', { status: value.status, code: value.code, actions: Array.isArray(value.actions) ? value.actions : [] })
      if (name === 'done') done = value
    }
    name = 'message'; data = []; bytes = 0
  }
  function line(text) {
    if (text === '') { dispatch(); return }
    bytes += encoder.encode(text).byteLength + 1
    if (bytes > maxFrameBytes) throw fail('A response event exceeded the stream size limit.')
    if (text.startsWith(':')) return
    const colon = text.indexOf(':'), field = colon < 0 ? text : text.slice(0, colon)
    let value = colon < 0 ? '' : text.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') name = value
    else if (field === 'data') data.push(value)
  }
  try {
    while (!done) {
      signal?.throwIfAborted()
      const { value, done: eof } = await reader.read()
      buffer += eof ? decoder.decode() : decoder.decode(value, { stream: true })
      let index
      while (!done && (index = buffer.search(/\r\n|\n|\r/)) >= 0) {
        if (!eof && buffer[index] === '\r' && index === buffer.length - 1) break   // a CRLF split across chunks
        const sep = buffer.startsWith('\r\n', index) ? 2 : 1
        const text = buffer.slice(0, index)
        buffer = buffer.slice(index + sep)
        line(text)
      }
      if (eof) { if (!done && buffer) { line(buffer); buffer = '' } if (!done && data.length) dispatch(); break }
    }
    if (!done) throw fail('The connection closed before the agent finished. Try again.')
    return done
  } finally {
    signal?.removeEventListener('abort', abort)
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export async function streamAgent(body, { signal, onEvent } = {}) {
  await ensureSession(); signal?.throwIfAborted()
  const send = () => fetch('/api/workspace/agent/stream', { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal, headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-Setup-Token': token() }, body: JSON.stringify(body) })
  let response = await send()
  if (response.status === 403) { await ensureSession(true); signal?.throwIfAborted(); response = await send() }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try { const value = await response.json(); message = value.error || message } catch { /* keep the status text */ }
    throw fail(message, { status: response.status })
  }
  return consumeAgentStream(response, { signal, onEvent })
}

// ---- turn state ------------------------------------------------------------------------------------------

export function newTurnState() {
  return { cards: [], status: 'working', pending: null, phase: '', offers: [], error: null }
}

export function lastLines(lines, n = 15) {
  return (Array.isArray(lines) ? lines : []).map((l) => String(l)).slice(-n)
}

const truncate = (text, n) => { const s = String(text ?? ''); return s.length > n ? `${s.slice(0, n - 1)}…` : s }

/** Fold one server event into the turn's cards. Large results are kept as short previews (chats live in localStorage). */
export function reduceAgentEvent(state, name, data = {}) {
  const tool = (id) => (id ? state.cards.find((c) => c.type === 'tool' && c.id === id) : null)
  if (name === 'plan') {
    if (data.phase) state.phase = data.phase
    if (Array.isArray(data.offers)) state.offers = data.offers.slice(0, 4)
    if (data.note) state.cards.push({ type: 'note', text: truncate(data.note, 300), status: data.status || '' })
    for (const a of data.auto || []) state.cards.push({ type: 'note', text: truncate(a.reason, 300), status: 'auto' })
  } else if (name === 'tool_start') {
    state.cards.push({ type: 'tool', id: data.id, tool: data.tool, label: data.label || data.tool, args: data.arguments || {}, cost: data.cost || 'free', simulated: !!data.simulated, status: 'running', log: [], started: Date.now() })
  } else if (name === 'tool_progress') {
    const card = tool(data.id)
    if (card) Object.assign(card, { log: lastLines(data.log_tail), elapsed_s: data.elapsed_s ?? card.elapsed_s, job_id: data.job_id || card.job_id })
  } else if (name === 'tool_result') {
    let card = tool(data.id)
    if (!card) { card = { type: 'tool', id: data.id || `r${state.cards.length}`, tool: data.tool, label: data.tool, args: {}, cost: 'free', log: [] }; state.cards.push(card) }
    Object.assign(card, { status: data.status || 'completed', duration_ms: data.duration_ms ?? card.duration_ms, error: data.error ? truncate(data.error, 800) : undefined, preview: data.preview ? truncate(data.preview, 2000) : data.result?.message ? truncate(data.result.message, 400) : card.preview })
    if (data.simulated != null) card.simulated = !!data.simulated
  } else if (name === 'artifact') {
    state.cards.push({ type: 'artifact', ...data })
  } else if (name === 'approval_request') {
    state.pending = data
    state.cards.push({ type: 'approval', card: data, answered: null })
  } else if (name === 'error') {
    state.status = 'error'
    state.error = { message: data.message || 'Something went wrong.', status: data.status, code: data.code, actions: data.actions || [] }
  } else if (name === 'done') {
    state.status = data.status || 'complete'
    state.message = data.message || ''
    state.suggestions = data.suggestions || []
    if (data.status !== 'waiting') state.pending = null
  }
  return state
}

/** Mark the card a user answered, so it shows what they chose and cannot be answered twice. */
export function markAnswered(state, pendingId, label) {
  const card = state.cards.find((c) => c.type === 'approval' && c.card?.id === pendingId)
  if (card) card.answered = label
  if (state.pending?.id === pendingId) state.pending = null
  return state
}

// ---- labels ----------------------------------------------------------------------------------------------

const SIMULATED = new Set(['market_test', 'run_test', 'study', 'pitch', 'email_test', 'website_test', 'results', 'compare_runs', 'ask_buyers', 'open_view', 'predict', 'ideas', 'quickstart', 'design_audience'])

/** Cards derived from simulated buyers carry a Simulated badge: decided by the tool, never by the model's words. */
export function isSimulated(tool, flag) {
  return typeof flag === 'boolean' ? flag || SIMULATED.has(tool) : SIMULATED.has(tool)
}

export function costLabel(cost) {
  return { free: 'Free', outside: 'Contacts the web', spend: 'Uses model calls' }[cost] || 'Free'
}

export function usd(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(2)}` : 'unknown'
}

export function durationText(ms) {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  const s = Math.round(ms / 1000)
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`
}

const STEP_NAMES = { people: 'Create the people', rounds: 'Social rounds', feed_test: 'Feed test', survey: 'Survey', pitch: 'Pitch', email_test: 'Emails', panel: 'Analyst panel', report: 'Report', test: 'Test', study: 'Study', focus_group: 'Focus group', answer: 'Answer', profile: 'Read the product', visitors: 'Website visitors', vision: 'Look at the creatives', labels: 'Label the ads', profiles: 'Grounded profiles' }

export function stepRows(steps) {
  return Object.entries(steps || {}).filter(([, n]) => Number(n) > 0).map(([key, n]) => ({ key, label: STEP_NAMES[key] || key.replaceAll('_', ' '), calls: Number(n) }))
}

export function argsPreview(args, max = 600) {
  try { return truncate(JSON.stringify(args ?? {}, null, 1), max) } catch { return '' }
}

// ---- forms -----------------------------------------------------------------------------------------------

export function formErrors(fields, values) {
  const errors = {}
  for (const f of fields || []) {
    const v = values?.[f.name]
    const empty = v == null || (typeof v === 'string' && !v.trim()) || (Array.isArray(v) && !v.length)
    if (f.required && empty) errors[f.name] = 'Required'
    else if (!empty && f.type === 'number' && !Number.isFinite(Number(v))) errors[f.name] = 'Enter a number'
    else if (!empty && f.type === 'select' && f.options?.length && !f.options.some((o) => o.value === v)) errors[f.name] = 'Choose an option'
  }
  return errors
}

// ---- audience table ----------------------------------------------------------------------------------------

export const WELL_COVERED = ['united states', 'usa', 'us', 'united kingdom', 'uk', 'gb', 'great britain', 'england', 'scotland', 'wales', 'canada', 'ca', 'australia', 'au', 'new zealand', 'nz', 'ireland', 'ie']

export function blankSegment() {
  return { label: '', count: 10, country: '', cities: [], age_min: 18, age_max: 65, gender_mix: 'balanced', platforms: [], notes: '', communities: [] }
}

export function listText(value) {
  return Array.isArray(value) ? value.join(', ') : String(value || '')
}

export function parseList(text) {
  return String(text || '').split(/[,\n]/).map((s) => s.trim()).filter(Boolean).slice(0, 20)
}

export function segmentTotals(segments) {
  const rows = (segments || []).filter((s) => s && String(s.label || '').trim())
  return { people: rows.reduce((n, s) => n + Math.max(0, Math.round(Number(s.count) || 0)), 0), segments: rows.length, countries: new Set(rows.map((s) => String(s.country || '').trim().toLowerCase()).filter(Boolean)).size }
}

/** Instant flags while editing (the server's fit check is the authority and replaces these when it answers). */
export function segmentFlags(segments) {
  const rows = (segments || []).filter((s) => s && String(s.label || '').trim())
  const flags = []
  const thin = rows.filter((s) => (Number(s.count) || 0) < 10)
  if (rows.length >= 2 && thin.length) flags.push({ code: 'small_segments', text: `${thin.length} of ${rows.length} segments have fewer than 10 people (${thin.map((s) => s.label).slice(0, 3).join(', ')}).` })
  const total = segmentTotals(rows).people
  const placed = rows.filter((s) => String(s.country || '').trim())
  const less = placed.filter((s) => !WELL_COVERED.includes(String(s.country).trim().toLowerCase())).reduce((n, s) => n + (Number(s.count) || 0), 0)
  const known = placed.reduce((n, s) => n + (Number(s.count) || 0), 0)
  if (known && less * 2 >= known) flags.push({ code: 'less_covered_markets', text: `${Math.round((100 * less) / (known || total || 1))}% of the people are in markets the models represent less well.` })
  return flags
}

// ---- chat integration ---------------------------------------------------------------------------------------

/** The agent is on unless this browser opted out (localStorage mm-chat-agent = "0"). */
export function agentChatEnabled(storage = globalThis.localStorage) {
  try { return storage?.getItem('mm-chat-agent') !== '0' } catch { return true }
}

/** The conversation the agent sees: newest messages within the server's limits. */
export function agentHistory(messages, { maxMessages = 25, maxChars = 44000 } = {}) {
  const out = []
  let remaining = maxChars
  for (const m of [...(messages || [])].reverse()) {
    if (!m || !['user', 'assistant'].includes(m.role) || !String(m.content || '').trim()) continue
    const content = String(m.content).slice(0, 11900)
    if (content.length > remaining) break
    out.unshift({ role: m.role, content })
    remaining -= content.length
    if (out.length >= maxMessages) break
  }
  while (out.length && out[0].role !== 'user') out.shift()
  return out
}

/** The compare message shape the chat already renders (an embedded CompareRuns), from a compare_runs artifact. */
export function compareFromCards(cards) {
  const found = [...(cards || [])].reverse().find((c) => c.type === 'artifact' && c.kind === 'compare' && c.compare?.a && c.compare?.b)
  return found ? { a: found.compare.a, b: found.compare.b } : null
}

export function answerLabel(card, answer) {
  if (card?.kind === 'form') return answer?.cancel ? 'Cancelled' : 'Sent'
  if (card?.kind === 'audience') return answer?.cancel ? 'Cancelled' : 'Audience confirmed'
  const option = (card?.options || []).find((o) => o.value === (answer?.decision ?? answer?.choice))
  return option ? option.label : 'Answered'
}
