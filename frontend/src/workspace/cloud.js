import { ref } from 'vue'
export const cloudAccount = ref(null)
export const cloudSyncError = ref('')
const STORE = 'mm-conversations-v1'
let revision = 0, timer, saveTask = null, dirty = false, polling = false
const headers = () => ({ 'Content-Type': 'application/json', 'X-CSRF-Token': cloudAccount.value.csrf, 'X-MM-Workspace': cloudAccount.value.workspace.id })
const read = () => { try { const value = JSON.parse(localStorage.getItem(STORE) || '[]'); return Array.isArray(value) ? value : [] } catch { return [] } }
export function mergeChats(remote, local) {
  const map = new Map(remote.map(chat => [chat.id, chat]))
  for (const chat of local) {
    const other = map.get(chat.id)
    if (!other) { map.set(chat.id, chat); continue }
    const newer = Number(chat.updated) >= Number(other.updated) ? chat : other, older = newer === chat ? other : chat
    const authors = new Map((other.messages || []).filter(message => message.author).map(message => [message.id, message.author]))
    const messages = new Map()
    for (const [index, message] of [...(older.messages || []), ...(newer.messages || [])].entries()) {
      const key = message.id || `legacy:${index}:${message.role}:${message.content}`
      messages.set(key, { ...message, ...(authors.has(message.id) ? { author: authors.get(message.id) } : {}) })
    }
    map.set(chat.id, { ...newer, messages: [...messages.values()] })
  }
  return [...map.values()].sort((a, b) => b.updated - a.updated)
}
function cache(chats) { localStorage.setItem(STORE, JSON.stringify(chats)); window.dispatchEvent(new Event('mm-chats-loaded')) }
async function request(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(10000), ...options, headers: { ...headers(), ...(options.headers || {}) } })
  const data = await response.json()
  if (!response.ok) throw Object.assign(new Error(data.error || 'Shared chats could not be synchronized.'), { status: response.status })
  return data
}
async function fetchChats(conditional = false) {
  const value = await request('/auth/chats' + (conditional ? `?after_revision=${revision}` : ''))
  revision = value.revision
  return value
}
export async function initializeCloud() {
  try {
    const response = await fetch('/auth/session', { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(5000) })
    if (!response.ok || !response.headers.get('Content-Type')?.includes('application/json')) return
    const data = await response.json()
    if (!data.account?.id || !data.workspace?.id || !data.csrf) return
    cloudAccount.value = data
    cache((await fetchChats()).chats)
    window.addEventListener('mm-chats-updated', scheduleCloudSync)
    setInterval(refreshCloudChats, 3000)
  } catch { if (cloudAccount.value) cloudSyncError.value = 'Shared chats could not be loaded. Refresh to retry.' }
}
export function scheduleCloudSync() {
  if (!cloudAccount.value) return
  dirty = true; clearTimeout(timer); timer = setTimeout(syncCloudChats, 250)
}
export function syncCloudChats() {
  if (saveTask) return saveTask
  if (!dirty || !cloudAccount.value) return Promise.resolve()
  saveTask = (async () => {
    try {
      while (dirty) {
        dirty = false
        let chats = read(), value
        try { value = await request('/auth/chats', { method: 'PUT', body: JSON.stringify({ chats, revision }) }) }
        catch (error) {
          if (error.status !== 409) throw error
          const remote = await fetchChats(); chats = mergeChats(remote.chats, read()); cache(chats)
          value = await request('/auth/chats', { method: 'PUT', body: JSON.stringify({ chats, revision }) })
        }
        revision = value.revision
        const canonical = value.chats || chats, latest = mergeChats(canonical, read())
        cache(latest); cloudSyncError.value = ''
      }
    } catch (error) { cloudSyncError.value = `Saved in this browser. ${error.message}`; dirty = true }
    finally { saveTask = null }
  })()
  return saveTask
}
export function retryCloudSync() { dirty = true; return syncCloudChats() }
export async function postTeamNote(chatId, text) {
  if (!cloudAccount.value) throw new Error('Team notes require a signed-in workspace.')
  const chats = read()
  if (!chats.some(chat => chat.id === chatId)) {
    chats.unshift({ id: chatId, title: text.slice(0, 80), updated: Date.now(), messages: [] }); cache(chats)
  }
  dirty = true; clearTimeout(timer); await syncCloudChats()
  if (cloudSyncError.value) throw new Error(cloudSyncError.value)
  const value = await request('/auth/chat-notes', { method: 'POST', body: JSON.stringify({ chat_id: chatId, text }) })
  revision = value.revision
  const merged = mergeChats([value.chat], read()); cache(merged)
  return merged.find(chat => chat.id === chatId)
}
async function refreshCloudChats() {
  if (!cloudAccount.value || saveTask || dirty || polling || document.hidden) return
  polling = true
  try {
    const data = await fetchChats(true)
    if (!data.unchanged) cache(mergeChats(data.chats, read()))
    cloudSyncError.value = ''
  } catch { cloudSyncError.value = 'Shared chats could not be refreshed. Your browser copy is still available.' }
  finally { polling = false }
}
