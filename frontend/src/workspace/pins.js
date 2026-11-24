// Saved runs pinned to the top of the sidebar: stored per person and workspace in the database, cached in
// this browser. A browser list from before the database is uploaded once, if the database has none yet.
import { ref, watch } from 'vue'

const KEY = 'mm-pinned-runs'
const IMPORTED = 'mm-pinned-runs-imported'
const read = () => {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}
export const pins = ref(read())
let save = null, loading = false

watch(pins, (v) => {
  try {
    localStorage.setItem(KEY, JSON.stringify(v))
  } catch {
    /* pins hold for this page */
  }
  if (save && !loading) save(v).catch(() => { /* kept in this browser; saved again on the next change */ })
}, { deep: true })

export function togglePin(name) {
  if (!name) return
  pins.value = pins.value.includes(name) ? pins.value.filter((k) => k !== name) : [name, ...pins.value]
}

// key: the workspace these pins belong to; fetcher(path, {method, body}) -> parsed data (api.js `api`).
export async function loadPins(key, fetcher) {
  save = (list) => fetcher('/api/workspace/pins', { method: 'PUT', body: { pins: list } })
  const stored = await fetcher('/api/workspace/pins')
  let marker = ''
  try { marker = localStorage.getItem(IMPORTED) || '' } catch { /* private window */ }
  loading = true
  try {
    if (!stored.pins.length && !marker && read().length) {
      pins.value = (await save(read())).pins
    } else {
      pins.value = stored.pins
    }
    try { localStorage.setItem(IMPORTED, key) } catch { /* the server list wins next time anyway */ }
  } finally {
    loading = false
  }
}
