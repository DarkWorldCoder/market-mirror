// Chats live in the workspace database. The browser keeps a cache under the old localStorage key
// (mm-conversations-v1), so the chat screen and sidebar keep reading and writing it as before; this module
// uploads the cache once, then saves each changed chat with its revision and pulls teammates' changes.
import { ref } from 'vue'
import { mergeChats } from './cloud.js'

export const STORE = 'mm-conversations-v1'
const OWNER = 'mm-conversations-owner'   // which workspace the cache belongs to
const BROWSER = 'mm-browser-id'
export const chatSyncError = ref('')
export const chatSyncState = ref('idle')  // idle | syncing | synced | read-only | offline

const storage = () => globalThis.localStorage
function read() { try { const v = JSON.parse(storage().getItem(STORE) || '[]'); return Array.isArray(v) ? v : [] } catch { return [] } }
function write(chats) { try { storage().setItem(STORE, JSON.stringify(chats)) } catch { /* the database copy is still saved */ } }

export function browserId() {
  let id = ''
  try { id = storage().getItem(BROWSER) || '' } catch { /* private window */ }
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
    id = 'b' + Array.from(globalThis.crypto.getRandomValues(new Uint8Array(12)), b => b.toString(16).padStart(2, '0')).join('')
    try { storage().setItem(BROWSER, id) } catch { /* a new id next time only repeats an import the server skips */ }
  }
  return id
}

// The cache may be uploaded only into the workspace it belongs to. A cache from before the database existed has
// no owner and goes to the first workspace this browser opens; a cache from another workspace is dropped.
export function cachePlan(owner, key) {
  if (!owner) return { clear: false, upload: true }
  if (owner === key) return { clear: false, upload: true }
  return { clear: true, upload: false }
}

// Chats edited here since the last save: not yet on the server, or newer than the copy we saved or pulled.
export function changedChats(local, known) {
  return local.filter(chat => chat && chat.id && Array.isArray(chat.messages) && chat.messages.length &&
    (!known.has(chat.id) || Number(chat.updated) > known.get(chat.id).updated))
}

// Server chats replace cached ones, except chats with unsaved local edits; local-only chats stay (to be saved).
export function mergeIntoCache(server, local, dirty) {
  const map = new Map(local.map(chat => [chat.id, chat]))
  for (const chat of server) {
    const mine = map.get(chat.id)
    map.set(chat.id, mine && dirty.has(chat.id) ? mergeChats([chat], [mine])[0] : chat)
  }
  return [...map.values()].sort((a, b) => Number(b.updated) - Number(a.updated))
}

let request = null, known = new Map(), timer = null, poller = null, saving = null, again = false, lastPull = 0, active = ''

async function call(path, options = {}) {
  const response = await request(path, options)
  const data = (response.headers.get('Content-Type') || '').includes('json') ? await response.json() : {}
  if (!response.ok || data.success === false) throw Object.assign(new Error(data.error || `Request failed (${response.status})`), { status: response.status, data: data.data, code: data.code })
  return data.data
}

function remember(chat) { known.set(chat.id, { revision: chat.revision, updated: Number(chat.updated) }) }

async function pull(since) {
  const data = await call('/api/workspace/chats' + (since ? `?since=${since}` : ''))
  const local = read()
  const dirty = new Set(changedChats(local, known).map(chat => chat.id))
  for (const chat of data.chats) { remember(chat); lastPull = Math.max(lastPull, Number(chat.updated) || 0) }
  if (data.chats.length || !since) { write(mergeIntoCache(data.chats, local, dirty)); window.dispatchEvent(new Event('mm-chats-loaded')) }
  return data
}

async function saveOne(chat) {
  const base = known.get(chat.id)?.revision || 0
  try {
    return await call(`/api/workspace/chats/${encodeURIComponent(chat.id)}`, { method: 'PUT', body: { chat, base_revision: base } })
  } catch (error) {
    if (error.status !== 409 || !error.data?.current) throw error
    // A teammate saved first: keep both sets of messages and save on top of their revision.
    const merged = mergeChats([error.data.current], [chat])[0]
    return call(`/api/workspace/chats/${encodeURIComponent(chat.id)}`, { method: 'PUT', body: { chat: merged, base_revision: error.data.current.revision } })
  }
}

// A short line for the shell: what happened to the last save, and why.
export function syncStatusText(state, error) {
  if (state === 'read-only') return error || 'Read only. Your edits stay in this browser.'
  if (state === 'offline') return error || 'Saved in this browser only.'
  if (state === 'syncing') return 'Saving chats…'
  return ''
}

// Retry after the server comes back without restarting the app.
export function retryChatSync() {
  if (!request || chatSyncState.value === 'read-only') return Promise.resolve()
  chatSyncState.value = 'syncing'
  return pull(lastPull).then(() => pushChats()).catch(() => {})
}

export function pushChats() {
  if (!request || chatSyncState.value === 'read-only') return Promise.resolve()
  if (saving) { again = true; return saving }
  saving = (async () => {
    do {
      again = false
      for (const chat of changedChats(read(), known)) {
        try {
          const saved = await saveOne(chat)
          remember(saved)
          // Keep the server's ids and authors, but never overwrite edits made while this save was in flight.
          const cache = read(), index = cache.findIndex(item => item.id === saved.id)
          if (index >= 0 && Number(cache[index].updated) <= Number(chat.updated)) { cache[index] = saved; write(cache) }
          else if (index >= 0) known.set(saved.id, { revision: saved.revision, updated: Number(chat.updated) })
          chatSyncError.value = ''
        } catch (error) {
          if (error.status === 403 && error.code === 'role') { chatSyncState.value = 'read-only'; chatSyncError.value = 'You can read this workspace. Your edits stay in this browser.'; return }
          chatSyncState.value = 'offline'
          chatSyncError.value = `Saved in this browser only. ${error.message}`
          return
        }
      }
      chatSyncState.value = 'synced'
    } while (again)
  })().finally(() => { saving = null })
  return saving
}

function schedule() { clearTimeout(timer); timer = setTimeout(pushChats, 400) }

export function stopChatSync() {
  clearTimeout(timer); clearInterval(poller); window.removeEventListener('mm-chats-updated', schedule)
  request = null; known = new Map(); lastPull = 0; active = ''
}

// key: the workspace the cache belongs to; fetcher(path, {method, body}) -> Response with auth headers;
// poll: also pull teammates' changes every 15 s (team mode).
export async function startChatSync({ key, fetcher, canWrite, poll }) {
  if (active === key) return
  stopChatSync()
  active = key; request = (path, { method = 'GET', body } = {}) => fetcher(path, { method, ...(body ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } } : {}) })
  chatSyncState.value = canWrite ? 'syncing' : 'read-only'
  let owner = ''
  try { owner = storage().getItem(OWNER) || '' } catch { /* no storage: nothing to import */ }
  const plan = cachePlan(owner, key)
  if (plan.clear) { write([]); window.dispatchEvent(new Event('mm-chats-loaded')) }
  try {
    const first = await pull()
    if (canWrite && plan.upload) {
      const source = browserId()
      const label = 'browser-chats:' + source
      const local = read().filter(chat => chat && Array.isArray(chat.messages) && chat.messages.length && !known.has(chat.id))
      if (!first.imported_sources.includes(label) && local.length) {
        await call('/api/workspace/chats/import', { method: 'POST', body: { source, chats: local } })
        await pull()
      } else if (!first.imported_sources.includes(label)) {
        await call('/api/workspace/chats/import', { method: 'POST', body: { source, chats: [] } })
      }
    }
    try { storage().setItem(OWNER, key) } catch { /* next start repeats an import the server skips */ }
    chatSyncError.value = ''
    if (canWrite) { await pushChats(); window.addEventListener('mm-chats-updated', schedule) }
    if (poll) poller = setInterval(() => { if (!document.hidden && !saving) pull(lastPull).catch(() => { chatSyncState.value = 'offline' }) }, 15000)
    if (chatSyncState.value === 'syncing') chatSyncState.value = 'synced'
  } catch (error) {
    chatSyncState.value = 'offline'
    chatSyncError.value = `Chats are saved in this browser until the server answers. ${error.message}`
  }
}
