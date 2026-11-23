// Token-aware calls for the workspace. The local app stores the setup token in this tab's session storage
// (see Home.vue); every /api/runs and /api/workflows call needs it. Other engine routes are loopback-only.
const KEY = 'marketmirror-session'

export function token() {
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

export async function api(path, options = {}) {
  const headers = { 'X-Setup-Token': token(), ...(options.headers || {}) }
  if (options.body && typeof options.body !== 'string') {
    headers['Content-Type'] = 'application/json'
    options = { ...options, body: JSON.stringify(options.body) }
  }
  const response = await fetch(path, { ...options, headers })
  const type = response.headers.get('Content-Type') || ''
  const data = type.includes('json') ? await response.json() : await response.text()
  if (!response.ok || (data && data.success === false)) {
    throw new Error((data && data.error) || `Request failed (${response.status})`)
  }
  return data && data.success !== undefined ? data.data : data
}

export async function download(run, file) {
  const response = await fetch(`/api/runs/${encodeURIComponent(run)}/files/${encodeURIComponent(file)}?download=1`, {
    headers: { 'X-Setup-Token': token() }
  })
  if (!response.ok) throw new Error('Download failed')
  const url = URL.createObjectURL(await response.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: file })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export async function openHtml(run, file) {
  const html = await api(`/api/runs/${encodeURIComponent(run)}/files/${encodeURIComponent(file)}`)
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
  window.open(url, '_blank', 'noopener')
}
