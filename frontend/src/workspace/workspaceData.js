// Starts the database-backed workspace data (chats, pins) once we know who is using the app, and restarts it
// when the person signs in or out or switches workspace.
import { api, authHeaders, ensureSession } from './api.js'
import { canEdit, signedIn, teamMode, workspaceKey } from './account.js'
import { cloudAccount } from './cloud.js'
import { startChatSync, stopChatSync } from './chatSync.js'
import { loadPins } from './pins.js'

const fetcher = (path, options = {}) => fetch(path, {
  credentials: 'same-origin', cache: 'no-store', ...options,
  headers: { ...(options.headers || {}), ...authHeaders() }
})

export async function startWorkspaceData() {
  // The hosted account gateway (cloud/) keeps chats in its own store; nothing to do here then.
  if (cloudAccount.value) return
  if (teamMode.value && !signedIn.value) { stopChatSync(); return }
  try { await ensureSession() } catch { return }
  startChatSync({ key: workspaceKey.value, fetcher, canWrite: canEdit.value, poll: signedIn.value })
  loadPins(workspaceKey.value, api).catch(() => { /* pins stay in this browser */ })
}

let listening = false
export function watchAccount() {
  if (listening) return
  listening = true
  window.addEventListener('mm-account-changed', () => { startWorkspaceData() })
}
