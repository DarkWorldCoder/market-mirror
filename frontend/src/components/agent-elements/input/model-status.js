// Plain status words for the chat model picker. The server sends `status` with each model.
const STATUS = {
  connected: { label: 'Connected', tone: 'ok' },
  configured: { label: 'Key saved', tone: 'neutral' },
  connect_on_first_use: { label: 'Connects on first use', tone: 'neutral' },
  key_rejected: { label: 'Key rejected', tone: 'bad' },
  needs_connection: { label: 'Connect', tone: 'neutral' }
}

export function modelStatus(model) {
  const id = STATUS[model?.status] ? model.status
    : model?.available === false ? 'needs_connection'
      : model?.connection_backend ? 'connected' : 'configured'
  return { id, ...STATUS[id] }
}

// The Claude Code login to offer when an API key was rejected: a connected one first, then one that connects on first use.
export function claudeLoginFallback(models = []) {
  const logins = models.filter(m => m?.connection_backend === 'claude' && m.available !== false)
  const rank = m => (m.status === 'connected' ? 0 : m.status === 'connect_on_first_use' ? 1 : 2) + (m.model === 'sonnet' ? 0 : 0.5)
  return logins.filter(m => rank(m) < 2).sort((a, b) => rank(a) - rank(b))[0] || null
}

export function rejectedModel(models = []) {
  return models.find(m => m?.status === 'key_rejected') || null
}
