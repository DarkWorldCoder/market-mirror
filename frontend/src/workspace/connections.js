// Pure helpers for the Connections page and the Models settings: status words, tool hints, form checks and the
// model cards. No network calls here, so they are tested in node (src/workspace/__tests__/connections.test.js).

/** A saved MCP server's state as a dot colour and a plain label. */
export function connectorStatus(connector) {
  const status = connector?.status
  if (status === 'connected') return { tone: 'ok', label: 'Connected' }
  if (status === 'auth_required') return { tone: 'error', label: 'Sign-in failed' }
  if (status === 'error') return { tone: 'error', label: 'Error' }
  return { tone: 'idle', label: 'Not checked' }
}

/** What a tool says it does, from the hints its server declares. Only read-only tools can run in chat. */
export function toolHint(tool) {
  if (tool?.read_only) return { id: 'read', label: 'Read-only', usable: true }
  if (tool?.destructive) return { id: 'destructive', label: 'Can change or delete data', usable: false }
  if (tool?.open_world) return { id: 'writes', label: 'Acts outside this app', usable: false }
  return { id: 'writes', label: 'May change data', usable: false }
}

const MCP_TRANSPORT = 'Streamable HTTP'
export function transportLabel() { return MCP_TRANSPORT }

/** Field errors for the Add MCP server form, in plain words. Empty object when the draft can be checked. */
export function validateServerDraft(draft = {}) {
  const errors = {}
  const name = String(draft.name || '').trim()
  const url = String(draft.url || '').trim()
  if (!name) errors.name = 'Give the server a name you will recognise.'
  else if (name.length > 100) errors.name = 'Use 100 characters or fewer.'
  if (!url) errors.url = 'Paste the server address.'
  else {
    let parsed = null
    try { parsed = new URL(url) } catch { errors.url = 'This does not look like a web address. It should start with https://' }
    if (parsed) {
      const host = parsed.hostname.toLowerCase()
      if (parsed.protocol !== 'https:') errors.url = 'Use an address that starts with https://'
      else if (parsed.username || parsed.password) errors.url = 'Remove the user name or password from the address. Put a token in the token field instead.'
      else if (parsed.search || parsed.hash) errors.url = 'Remove the part after ? or # from the address.'
      else if (host === 'localhost' || host.endsWith('.localhost') || /^127\./.test(host) || host === '[::1]' || /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) {
        errors.url = 'Servers on this computer or a private network cannot be added here. Use a public https address.'
      }
    }
  }
  if (String(draft.token || '').length > 8192) errors.token = 'This token is too long.'
  return errors
}

/** "just now", "5 min ago", "3 h ago", or a date. `seconds` is a Unix time in seconds. */
export function relativeTime(seconds, now = Date.now()) {
  if (!seconds) return ''
  const diff = Math.max(0, Math.round(now / 1000 - Number(seconds)))
  if (diff < 45) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`
  return new Date(Number(seconds) * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Counts for the Settings > Connections summary and the page header. */
export function connectionsSummary(connectors = [], models = []) {
  const servers = connectors.length
  const connected = connectors.filter(c => c.status === 'connected').length
  const failing = connectors.filter(c => c.status === 'error' || c.status === 'auth_required').length
  const toolsOn = connectors.filter(c => c.enabled).reduce((sum, c) => sum + (c.tools || []).filter(t => t.read_only && (c.allowed_tools || []).includes(t.name)).length, 0)
  const modelsReady = models.filter(m => m.available && m.status !== 'key_rejected').length
  return { servers, connected, failing, toolsOn, modelsReady }
}

// ---- models --------------------------------------------------------------------------------------------------

export const MODEL_STATUS = {
  connected: { label: 'Connected', tone: 'ok' },
  in_use: { label: 'In use', tone: 'ok' },
  configured: { label: 'Key saved', tone: 'info' },
  connect_on_first_use: { label: 'Connects on first use', tone: 'info' },
  key_rejected: { label: 'Key rejected', tone: 'error' },
  needs_connection: { label: 'Not set up', tone: 'idle' },
  not_set_up: { label: 'Not set up', tone: 'idle' },
  no_key_needed: { label: 'No key needed', tone: 'idle' }
}
export function modelStatus(status) { return MODEL_STATUS[status] || MODEL_STATUS.not_set_up }

const LOGIN_LABELS = { claude: 'Claude Code login', codex: 'Codex login', antigravity: 'Antigravity login', gemini: 'Gemini CLI login' }
const LOGIN_HELP = {
  claude: 'Uses the Claude account you are signed in to on this computer. No API key.',
  codex: 'Uses your ChatGPT account through the Codex app on this computer. No API key.',
  antigravity: 'Uses Gemini models through your Antigravity sign-in on this computer. No API key.',
  gemini: 'Uses your Gemini CLI sign-in on this computer. No API key.'
}
const API_HELP = {
  claude: 'Claude models with your Anthropic API key.',
  openai: 'GPT models with your OpenAI API key.',
  gemini: 'Gemini models with your Google AI Studio key.',
  openrouter: 'Many model makers behind one key.',
  ollama: 'Free models running on your own computer with Ollama.',
  custom: 'Any server that speaks the OpenAI format, with its address and model name.'
}
const PROMINENT = ['claude', 'openai', 'gemini', 'openrouter', 'ollama', 'custom']
const RANK = { key_rejected: 0, connected: 1, in_use: 1, connect_on_first_use: 2, configured: 3, needs_connection: 4, not_set_up: 5, no_key_needed: 5 }

function bestStatus(statuses) {
  const order = ['connected', 'connect_on_first_use', 'configured', 'key_rejected', 'needs_connection']
  return order.find(s => statuses.includes(s)) || 'needs_connection'
}

/**
 * One card per way of reaching models: signed-in apps on this computer, then API providers.
 * `settings` is GET /api/workspace/settings `llm`; `catalog` is GET /api/workspace/models `models`;
 * `tested` maps provider id to a check result from this session.
 */
export function modelCards(settings = {}, catalog = [], tested = {}) {
  const gateway = settings.gateway || ''
  const logins = new Map()
  for (const entry of catalog) {
    const backend = entry.connection_backend
    if (!backend) continue
    const card = logins.get(backend) || { id: `login:${backend}`, kind: 'login', backend, name: LOGIN_LABELS[backend] || `${backend} login`, help: LOGIN_HELP[backend] || 'Uses a sign-in on this computer. No API key.', statuses: [], models: [] }
    card.statuses.push(entry.status)
    card.models.push(entry.model)
    logins.set(backend, card)
  }
  const loginCards = [...logins.values()].map(card => {
    const status = bestStatus(card.statuses)
    return { id: card.id, kind: 'login', backend: card.backend, name: card.name, help: card.help, icon: card.backend,
      status, inUse: gateway === card.backend, models: [...new Set(card.models)] }
  })
  const apiCards = (settings.providers || []).map(p => {
    const entries = catalog.filter(m => !m.connection_backend && m.provider === p.id)
    let status = p.key_configured ? 'configured' : ['ollama', 'custom'].includes(p.id) ? 'not_set_up' : 'not_set_up'
    if (entries.some(m => m.status === 'key_rejected')) status = 'key_rejected'
    else if (p.id === 'ollama' && entries.some(m => m.available)) status = 'connected'
    const check = tested[p.id]
    if (check?.status === 'connected') status = 'connected'
    else if (check?.status === 'key_rejected') status = 'key_rejected'
    return { id: `api:${p.id}`, kind: 'api', provider: p.id, name: p.id === 'custom' ? 'Your own model server' : p.label,
      help: API_HELP[p.id] || `${p.label} models with your API key.`, icon: p.id, status,
      inUse: !gateway && settings.provider === p.id, model: p.model, base_url: p.base_url, key_configured: !!p.key_configured,
      keyOptional: ['ollama', 'custom'].includes(p.id), prominent: PROMINENT.includes(p.id) }
  })
  const sortApi = (a, b) => Number(b.inUse) - Number(a.inUse) || (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9) || Number(b.prominent) - Number(a.prominent)
  return { logins: loginCards.sort((a, b) => Number(b.inUse) - Number(a.inUse) || (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9)), apis: apiCards.sort(sortApi) }
}

/** Which API cards to show before "Show all providers": the one in use, anything set up, and the common ones. */
export function visibleApiCards(cards, showAll) {
  if (showAll) return cards
  return cards.filter(card => card.inUse || card.status !== 'not_set_up' || card.prominent)
}

/** The sentence at the top of the Models tab. */
export function inUseLine(settings = {}, cards = { logins: [], apis: [] }) {
  const login = cards.logins.find(c => c.inUse)
  if (login) return `New chats use your ${login.name}${settings.model ? ` (${settings.model})` : ''}.`
  const api = cards.apis.find(c => c.inUse)
  if (api) return `New chats use ${api.name}${settings.model ? ` (${settings.model})` : ''}.`
  return 'No default model is set yet. Pick one below.'
}
