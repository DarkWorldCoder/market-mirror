import test from 'node:test'
import assert from 'node:assert/strict'
import {
  connectionsSummary, connectorStatus, inUseLine, modelCards, modelStatus, relativeTime, toolHint, validateServerDraft, visibleApiCards
} from '../connections.js'

test('connector status words', () => {
  assert.deepEqual(connectorStatus({ status: 'connected' }), { tone: 'ok', label: 'Connected' })
  assert.deepEqual(connectorStatus({ status: 'auth_required' }), { tone: 'error', label: 'Sign-in failed' })
  assert.deepEqual(connectorStatus({ status: 'error' }), { tone: 'error', label: 'Error' })
  assert.deepEqual(connectorStatus({ status: 'not_tested' }), { tone: 'idle', label: 'Not checked' })
  assert.deepEqual(connectorStatus(null), { tone: 'idle', label: 'Not checked' })
})

test('tool hints follow the server annotations and only read-only tools are usable', () => {
  assert.equal(toolHint({ read_only: true }).usable, true)
  assert.equal(toolHint({ read_only: true, destructive: true }).id, 'read')
  assert.deepEqual(toolHint({ destructive: true }), { id: 'destructive', label: 'Can change or delete data', usable: false })
  assert.equal(toolHint({ open_world: true }).label, 'Acts outside this app')
  assert.equal(toolHint({}).label, 'May change data')
})

test('server form checks', () => {
  assert.deepEqual(validateServerDraft({ name: 'Ads', url: 'https://mcp.example.com/mcp' }), {})
  assert.match(validateServerDraft({ name: '', url: 'https://x.dev/mcp' }).name, /name/)
  assert.match(validateServerDraft({ name: 'A', url: '' }).url, /Paste/)
  assert.match(validateServerDraft({ name: 'A', url: 'not a url' }).url, /https:\/\//)
  assert.match(validateServerDraft({ name: 'A', url: 'http://mcp.example.com/mcp' }).url, /https:\/\//)
  assert.match(validateServerDraft({ name: 'A', url: 'https://u:p@mcp.example.com/mcp' }).url, /token field/)
  assert.match(validateServerDraft({ name: 'A', url: 'https://mcp.example.com/mcp?key=1' }).url, /after \?/)
  for (const url of ['https://localhost/mcp', 'https://127.0.0.1:5061/mcp', 'https://192.168.1.4/mcp', 'https://10.0.0.2/mcp', 'https://172.20.0.1/mcp']) {
    assert.match(validateServerDraft({ name: 'A', url }).url, /private network/, url)
  }
  assert.ok(validateServerDraft({ name: 'x'.repeat(101), url: 'https://a.dev' }).name)
})

test('relative time', () => {
  const now = 1_000_000 * 1000
  assert.equal(relativeTime(null, now), '')
  assert.equal(relativeTime(1_000_000 - 10, now), 'just now')
  assert.equal(relativeTime(1_000_000 - 300, now), '5 min ago')
  assert.equal(relativeTime(1_000_000 - 7200, now), '2 h ago')
  assert.ok(relativeTime(1_000_000 - 3 * 86400, now).length > 4)
})

test('summary counts only enabled read-only allowed tools', () => {
  const connectors = [
    { status: 'connected', enabled: true, allowed_tools: ['a', 'b'], tools: [{ name: 'a', read_only: true }, { name: 'b', read_only: false }, { name: 'c', read_only: true }] },
    { status: 'connected', enabled: false, allowed_tools: ['x'], tools: [{ name: 'x', read_only: true }] },
    { status: 'error', enabled: true, allowed_tools: [], tools: [] }
  ]
  const models = [{ available: true, status: 'connected' }, { available: false, status: 'key_rejected' }, { available: true, status: 'configured' }]
  assert.deepEqual(connectionsSummary(connectors, models), { servers: 3, connected: 2, failing: 1, toolsOn: 1, modelsReady: 2 })
})

test('model status labels', () => {
  assert.equal(modelStatus('configured').label, 'Key saved')
  assert.equal(modelStatus('connect_on_first_use').label, 'Connects on first use')
  assert.equal(modelStatus('key_rejected').label, 'Key rejected')
  assert.equal(modelStatus('needs_connection').label, 'Not set up')
  assert.equal(modelStatus('whatever').label, 'Not set up')
})

const settings = {
  provider: 'openai', model: 'gpt-4o-mini', gateway: null,
  providers: [
    { id: 'claude', label: 'Anthropic', key_configured: false, model: 'claude-haiku-4-5', base_url: 'https://api.anthropic.com/v1' },
    { id: 'openai', label: 'OpenAI', key_configured: true, model: 'gpt-4o-mini', base_url: 'https://api.openai.com/v1' },
    { id: 'groq', label: 'Groq', key_configured: false },
    { id: 'mistral', label: 'Mistral', key_configured: true },
    { id: 'ollama', label: 'Ollama', key_configured: false }
  ]
}
const catalog = [
  { provider: 'claude', model: 'sonnet', status: 'connect_on_first_use', connection_backend: 'claude', available: true },
  { provider: 'claude', model: 'haiku', status: 'connected', connection_backend: 'claude', available: true },
  { provider: 'codex', model: 'codex', status: 'needs_connection', connection_backend: 'codex', available: false },
  { provider: 'mistral', model: 'mistral-small', status: 'key_rejected', available: false },
  { provider: 'ollama', model: 'llama3.2', status: 'connected', available: true }
]

test('model cards: logins grouped with their best status, API providers with key state', () => {
  const cards = modelCards(settings, catalog)
  assert.deepEqual(cards.logins.map(c => [c.backend, c.status]), [['claude', 'connected'], ['codex', 'needs_connection']])
  assert.deepEqual(cards.logins[0].models, ['sonnet', 'haiku'])
  const byId = Object.fromEntries(cards.apis.map(c => [c.provider, c]))
  assert.equal(byId.openai.status, 'configured')
  assert.equal(byId.openai.inUse, true)
  assert.equal(byId.mistral.status, 'key_rejected')
  assert.equal(byId.ollama.status, 'connected')
  assert.equal(byId.claude.status, 'not_set_up')
  assert.equal(cards.apis[0].provider, 'openai')
})

test('a passing check this session marks the card connected', () => {
  const cards = modelCards(settings, catalog, { claude: { status: 'connected' }, openai: { status: 'key_rejected' } })
  const byId = Object.fromEntries(cards.apis.map(c => [c.provider, c]))
  assert.equal(byId.claude.status, 'connected')
  assert.equal(byId.openai.status, 'key_rejected')
})

test('a gateway in use wins the in-use line', () => {
  const cards = modelCards({ ...settings, gateway: 'claude', model: 'sonnet' }, catalog)
  assert.equal(cards.logins[0].inUse, true)
  assert.ok(cards.apis.every(c => !c.inUse))
  assert.equal(inUseLine({ model: 'sonnet' }, cards), 'New chats use your Claude Code login (sonnet).')
  assert.equal(inUseLine({}, { logins: [], apis: [] }), 'No default model is set yet. Pick one below.')
})

test('short provider list keeps set-up and common providers', () => {
  const cards = modelCards(settings, catalog).apis
  const short = visibleApiCards(cards, false).map(c => c.provider)
  assert.ok(short.includes('mistral'))
  assert.ok(short.includes('claude'))
  assert.ok(!short.includes('groq'))
  assert.equal(visibleApiCards(cards, true).length, cards.length)
})
