import { authHeaders, ensureSession } from './api.js'
import { signedIn } from './account.js'

const MAX_FRAME = 512 * 1024
const encoder = new TextEncoder()
const streamError = (message, status) => Object.assign(new Error(message), status ? { status } : {})

export async function consumeChatStream(response, { signal, onEvent, maxFrameBytes = MAX_FRAME } = {}) {
  if (!response.body) throw streamError('The response stream is unavailable. Refresh and try again.')
  const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', { fatal: true })
  let buffer = '', eventName = 'message', data = [], frameBytes = 0, result, finished = false
  const aborted = () => { reader.cancel(signal?.reason).catch(() => {}) }
  signal?.addEventListener('abort', aborted, { once: true })
  const checkAbort = () => signal?.throwIfAborted()
  function dispatch() {
    if (data.length && ['progress','result','error'].includes(eventName)) {
      let value
      try { value = JSON.parse(data.join('\n')) } catch { throw streamError('The response contained invalid stream data.') }
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw streamError('The response contained an invalid stream event.')
      if (eventName === 'error') throw streamError(typeof value.message === 'string' ? value.message : 'Could not complete this response.', value.status)
      if (eventName === 'result') { result = value; finished = true }
      else onEvent?.(value)
    }
    eventName = 'message'; data = []; frameBytes = 0
  }
  function line(value) {
    if (value === '') { dispatch(); return }
    frameBytes += encoder.encode(value).byteLength + 1
    if (frameBytes > maxFrameBytes) throw streamError('A response event exceeded the stream size limit.')
    if (value.startsWith(':')) return
    const colon = value.indexOf(':'), field = colon < 0 ? value : value.slice(0,colon)
    let content = colon < 0 ? '' : value.slice(colon + 1)
    if (content.startsWith(' ')) content = content.slice(1)
    if (field === 'event') eventName = content
    else if (field === 'data') data.push(content)
  }
  function drain(eof = false) {
    while (!finished) {
      const index = buffer.search(/[\r\n]/)
      if (index < 0) break
      if (!eof && buffer[index] === '\r' && index === buffer.length - 1) break
      const end = buffer[index] === '\r' && buffer[index + 1] === '\n' ? 2 : 1
      const value = buffer.slice(0,index); buffer = buffer.slice(index + end); line(value)
    }
    if (!finished && encoder.encode(buffer).byteLength + frameBytes > maxFrameBytes) throw streamError('A response event exceeded the stream size limit.')
    if (eof && !finished) { if (buffer) { line(buffer); buffer = '' }; if (data.length) dispatch() }
  }
  try {
    checkAbort()
    while (!finished) {
      const { value, done } = await reader.read(); checkAbort()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream:true })
      drain(done)
      if (done) break
    }
    if (!finished) throw streamError('The connection closed before an answer was received. Try again.')
    return result
  } finally {
    signal?.removeEventListener('abort', aborted)
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export async function streamChat(body, { signal, onEvent } = {}) {
  await ensureSession(); signal?.throwIfAborted()
  const encoded = JSON.stringify(body)
  const send = () => fetch('/api/workspace/chat/stream', { method:'POST', credentials:'same-origin', cache:'no-store', signal, headers:{'Content-Type':'application/json', Accept:'text/event-stream', ...authHeaders()}, body:encoded })
  let response = await send()
  // This guard response precedes model execution. No stream or model failure is replayed.
  if (response.status === 403 && !signedIn.value) { signal?.throwIfAborted(); await ensureSession(true); signal?.throwIfAborted(); response = await send() }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    if (response.headers.get('Content-Type')?.includes('json')) { try { const value = await response.json(); message = value.error || value.message || message } catch { /* Keep the HTTP status when an error body is not valid JSON. */ } }
    throw streamError(message,response.status)
  }
  if (!response.headers.get('Content-Type')?.includes('text/event-stream')) throw streamError('The server did not open a response stream. Refresh and try again.')
  return consumeChatStream(response,{signal,onEvent})
}
