import { ref } from 'vue'
import { accountHeaders, loadAccount, signedIn } from './account.js'
const sessionVersion = ref(0)
// Token-aware calls for the workspace. The local app stores the setup token in this tab's session storage
// (see Home.vue); every /api/runs and /api/workflows call needs it. Other engine routes are loopback-only.
const KEY = 'marketmirror-session'

export function token() {
  sessionVersion.value
  try {
    const fromHash = new URLSearchParams(location.hash.slice(1)).get('t')
    if (fromHash) {
      sessionStorage.setItem(KEY, fromHash)
      history.replaceState(history.state, '', location.pathname + location.search)
      return fromHash
    }
    return sessionStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

let sessionRequest = null
export async function ensureSession(force = false) {
  if (signedIn.value) return ''   // team mode: the session cookie and CSRF token stand in for the local token
  if (!force && token()) return token()
  if (sessionRequest) return sessionRequest
  sessionRequest = (async () => {
    const response = await fetch('/api/workspace/session', { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(8000) })
    if (!response.ok) throw new Error('Could not connect to the local MarketMirror service. Refresh to retry.')
    const value = await response.json()
    if (!value.success || !value.data?.token) throw new Error('The local connection could not be established. Refresh to retry.')
    sessionStorage.setItem(KEY, value.data.token)
    sessionVersion.value++
    return value.data.token
  })().finally(() => { sessionRequest = null })
  return sessionRequest
}

export async function api(path, options = {}) {
  await ensureSession()
  if (options.body && typeof options.body !== 'string') {
    options = { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, body: JSON.stringify(options.body) }
  }
  const send = () => fetch(path, { credentials: 'same-origin', ...options, headers: { ...(options.headers || {}), ...authHeaders() } })
  let response = await send()
  if (response.status === 403 && !signedIn.value) { await ensureSession(true); response = await send() }
  if (signedIn.value && (response.status === 401 || response.status === 409)) {
    // Signed out elsewhere, or removed from this workspace: refresh who we are so the app can react.
    const code = response.headers.get('Content-Type')?.includes('json') ? (await response.clone().json()).code : ''
    if (response.status === 401 || code === 'workspace_changed') loadAccount()
  }
  const type = response.headers.get('Content-Type') || ''
  const data = type.includes('json') ? await response.json() : await response.text()
  if (!response.ok || (data && data.success === false)) {
    throw new Error((data && data.error) || `Request failed (${response.status})`)
  }
  return data && data.success !== undefined ? data.data : data
}

// The local token, or in team mode the session's CSRF token and chosen workspace.
export function authHeaders() {
  return signedIn.value ? accountHeaders() : { 'X-Setup-Token': token() }
}

export async function download(run, file) {
  await ensureSession()
  const response = await fetch(`/api/runs/${encodeURIComponent(run)}/files/${encodeURIComponent(file)}?download=1`, {
    credentials: 'same-origin', headers: authHeaders()
  })
  if (!response.ok) throw new Error('Download failed')
  const url = URL.createObjectURL(await response.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: file })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export async function openHtml(run, file) {
  const html = await api(`/api/runs/${encodeURIComponent(run)}/files/${encodeURIComponent(file)}`)
  const wrapper = document.createElement('html')
  const frame = document.createElement('iframe')
  frame.setAttribute('sandbox', 'allow-scripts')
  frame.setAttribute('referrerpolicy', 'no-referrer')
  frame.setAttribute('title', 'Saved dashboard')
  frame.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;border:0'
  frame.srcdoc = String(html)
  wrapper.appendChild(frame)
  const url = URL.createObjectURL(new Blob(['<!doctype html>' + wrapper.outerHTML], { type: 'text/html' }))
  window.open(url, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
