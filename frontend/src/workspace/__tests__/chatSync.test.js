import test from 'node:test'
import assert from 'node:assert/strict'

// chatSync and account read browser globals lazily; give them minimal stand-ins.
const store = new Map()
globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) }
globalThis.window = { dispatchEvent() {}, addEventListener() {}, removeEventListener() {} }

const { browserId, cachePlan, changedChats, mergeIntoCache, startChatSync, stopChatSync, STORE } = await import('../chatSync.js')
const { invitationFromHash } = await import('../account.js')

const chat = (id, updated, messages = [{ id: `${id}-1`, role: 'user', content: 'hi' }], extra = {}) => ({ id, updated, title: id, messages, ...extra })

test('the browser cache is uploaded only into the workspace it belongs to', () => {
  assert.deepEqual(cachePlan('', 'local'), { clear: false, upload: true })          // from before the database
  assert.deepEqual(cachePlan('u1:ws1', 'u1:ws1'), { clear: false, upload: true })
  assert.deepEqual(cachePlan('u1:ws1', 'u1:ws2'), { clear: true, upload: false })   // never copy one team's chats into another
})

test('only chats edited since the last save are sent', () => {
  const known = new Map([['a', { revision: 2, updated: 100 }], ['b', { revision: 1, updated: 100 }]])
  const local = [chat('a', 100), chat('b', 150), chat('c', 10), chat('empty', 500, [])]
  assert.deepEqual(changedChats(local, known).map(c => c.id), ['b', 'c'])
})

test('server copies replace the cache unless this browser has unsaved edits', () => {
  const server = [chat('a', 200, [{ id: 'a-1', role: 'user', content: 'from teammate' }], { revision: 3 })]
  const local = [chat('a', 100, [{ id: 'a-1', role: 'user', content: 'old' }]), chat('mine', 50)]
  const clean = mergeIntoCache(server, local, new Set())
  assert.equal(clean.find(c => c.id === 'a').messages[0].content, 'from teammate')
  assert.ok(clean.some(c => c.id === 'mine'), 'chats not yet saved stay in the cache')
  const dirtyLocal = [chat('a', 300, [{ id: 'a-1', role: 'user', content: 'old' }, { id: 'a-2', role: 'user', content: 'new here' }])]
  const merged = mergeIntoCache(server, dirtyLocal, new Set(['a'])).find(c => c.id === 'a')
  assert.deepEqual(merged.messages.map(m => m.id), ['a-1', 'a-2'], 'both sides kept, merged by message id')
})

test('a browser id is stable and safe to send', () => {
  const id = browserId()
  assert.match(id, /^[A-Za-z0-9_-]{8,64}$/)
  assert.equal(browserId(), id)
})

test('invitation tokens are read from the link fragment only when well formed', () => {
  assert.equal(invitationFromHash('#invite=abcdefghijklmnopqrstuvwxyz0123'), 'abcdefghijklmnopqrstuvwxyz0123')
  assert.equal(invitationFromHash('#invite=short'), '')
  assert.equal(invitationFromHash('#invite=<script>alert(1)</script>xxxxxxxxxxxxxx'), '')
  assert.equal(invitationFromHash(''), '')
})

test('first start uploads browser chats once, then saves edits with their revision', async () => {
  store.clear()
  store.set(STORE, JSON.stringify([chat('old1', 100), chat('old2', 90)]))
  const server = new Map(), calls = []
  let imported = []
  const reply = (status, data) => ({ ok: status < 400, status, headers: { get: () => 'application/json' }, json: async () => ({ success: status < 400, data }) })
  const fetcher = async (path, { method = 'GET', body } = {}) => {
    calls.push(`${method} ${path.split('?')[0]}`)
    const value = body ? JSON.parse(body) : null
    if (path.startsWith('/api/workspace/chats/import')) {
      imported.push('browser-chats:' + value.source)
      for (const c of value.chats) server.set(c.id, { ...c, revision: 1 })
      return reply(201, { imported: value.chats.length, skipped: 0 })
    }
    if (method === 'PUT') {
      const current = server.get(value.chat.id)
      if (current && current.revision !== value.base_revision) return reply(409, { current })
      const saved = { ...value.chat, revision: (current?.revision || 0) + 1 }
      server.set(saved.id, saved)
      return reply(200, saved)
    }
    return reply(200, { chats: [...server.values()], imported_sources: imported })
  }
  await startChatSync({ key: 'local', fetcher, canWrite: true, poll: false })
  assert.deepEqual([...server.keys()].sort(), ['old1', 'old2'])
  assert.equal(store.get('mm-conversations-owner'), 'local')
  assert.ok(!calls.some(c => c.startsWith('PUT')), 'imported chats are not saved a second time')
  stopChatSync()
  await startChatSync({ key: 'local', fetcher, canWrite: true, poll: false })
  assert.equal(calls.filter(c => c === 'POST /api/workspace/chats/import').length, 1, 'the upload happens once per browser')
  // a teammate saved old1 meanwhile; this browser's edit is merged onto their revision instead of overwriting it
  server.set('old1', { ...server.get('old1'), revision: 5, messages: [...server.get('old1').messages, { id: 'team-1', role: 'user', content: 'teammate' }] })
  const cache = JSON.parse(store.get(STORE))
  cache[cache.findIndex(c => c.id === 'old1')] = chat('old1', Date.now(), [{ id: 'old1-1', role: 'user', content: 'hi' }, { id: 'me-1', role: 'user', content: 'mine' }])
  store.set(STORE, JSON.stringify(cache))
  const { pushChats } = await import('../chatSync.js')
  await pushChats()
  assert.deepEqual(server.get('old1').messages.map(m => m.id).sort(), ['me-1', 'old1-1', 'team-1'])
  assert.equal(server.get('old1').revision, 6)
  stopChatSync()
})
