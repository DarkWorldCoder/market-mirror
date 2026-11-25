// Who is using the app. Local mode: nobody signs in; the setup token from ./mm app is the key (api.js).
// Team mode (MM_ACCOUNTS=on on the server): a session cookie, a CSRF token for writes and the chosen workspace.
import { computed, ref } from 'vue'

const empty = { mode: 'unknown', account: null, workspace: null, workspaces: [], csrf: '', signups: 'closed', first_account: false }
export const account = ref({ ...empty })
// Set only when the server ends a session; a normal sign-out leaves it false.
export const sessionEnded = ref(false)
// A session check that fails for any reason other than "no accounts here".
export const accountError = ref('')
export const teamMode = computed(() => account.value.mode === 'accounts')
export const signedIn = computed(() => teamMode.value && !!account.value.account)
export const role = computed(() => (signedIn.value ? account.value.workspace?.role || 'viewer' : 'owner'))
export const canEdit = computed(() => role.value !== 'viewer')
export const isOwner = computed(() => role.value === 'owner')
// Which workspace the browser's chat cache belongs to; 'local' for the single-user app.
export const workspaceKey = computed(() => (signedIn.value && account.value.workspace ? `${account.value.account.id}:${account.value.workspace.id}` : 'local'))

export function accountHeaders() {
  if (!signedIn.value) return {}
  return { 'X-CSRF-Token': account.value.csrf, ...(account.value.workspace ? { 'X-MM-Workspace': account.value.workspace.id } : {}) }
}

export class AccountError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code }
}

async function call(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...accountHeaders() },
    ...(body ? { body: JSON.stringify(body) } : {})
  })
  const type = response.headers.get('Content-Type') || ''
  const data = type.includes('json') ? await response.json() : {}
  if (!response.ok || data.success === false) throw new AccountError(data.error || `Request failed (${response.status})`, response.status, data.code)
  return data.data
}

function apply(data) { if (data.account) sessionEnded.value = false; account.value = { ...empty, ...data }; window.dispatchEvent(new Event('mm-account-changed')); return account.value }

// A 401 in team mode: keep team mode but drop the person, so the router can
// send them to sign-in instead of silently falling back to local mode.
export function endSession() { sessionEnded.value = true; return apply({ mode: 'accounts', account: null }) }

export async function loadAccount() {
  accountError.value = ''
  try { return apply(await call('/api/auth/session')) }
  catch (error) {
    // Only a missing auth route means an older backend without accounts.
    if (error instanceof AccountError && error.status === 404) return apply({ mode: 'local' })
    accountError.value = 'Cannot reach the server. Check that MarketMirror is running, then retry.'
    return account.value
  }
}

export const signUp = (values) => call('/api/auth/signup', { method: 'POST', body: values }).then(apply)
export const signIn = (email, password) => call('/api/auth/login', { method: 'POST', body: { email, password } }).then(apply)
export const createWorkspace = (name) => call('/api/auth/workspaces', { method: 'POST', body: { name } }).then(apply)
export const selectWorkspace = (id) => call('/api/auth/workspaces/select', { method: 'POST', body: { id } }).then(apply)
export const acceptInvitation = (token) => call('/api/auth/invitations/accept', { method: 'POST', body: { token } }).then(apply)
export const previewInvitation = (token) => call(`/api/auth/invitations/${encodeURIComponent(token)}`)
export const changePassword = (current_password, new_password) => call('/api/auth/password', { method: 'POST', body: { current_password, new_password } }).then(apply)
export async function signOut() {
  try { await call('/api/auth/logout', { method: 'POST' }) } finally { apply({ mode: 'accounts', account: null }) }
}

// Team and workspace data share the same headers; api.js routes through here once someone is signed in.
export const team = {
  get: () => call('/api/team'),
  rename: (name) => call('/api/team/workspace', { method: 'PATCH', body: { name } }),
  setRole: (id, newRole) => call(`/api/team/members/${encodeURIComponent(id)}`, { method: 'PATCH', body: { role: newRole } }),
  remove: (id) => call(`/api/team/members/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  invite: (values) => call('/api/team/invitations', { method: 'POST', body: values }),
  revoke: (id) => call(`/api/team/invitations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

// An invitation link carries its token after '#', which never reaches the server's logs.
export function invitationFromHash(hash = globalThis.location?.hash || '') {
  const value = new URLSearchParams(String(hash).replace(/^#/, '')).get('invite') || ''
  return /^[A-Za-z0-9_-]{20,200}$/.test(value) ? value : ''
}
