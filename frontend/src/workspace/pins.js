// Saved runs pinned to the top of the sidebar: stored per person and workspace in the database, cached in
// this browser. A browser list from before the database is uploaded once, if the database has none yet.
import { ref, watch } from 'vue'

const KEY = 'mm-pinned-runs'
const IMPORTED = 'mm-pinned-runs-imported'

const same = (a, b) => a.length === b.length && a.every((value, index) => value === b[index])

export function createPinStore(storage) {
  const get = (key) => {
    try {
      return storage?.getItem(key) ?? null
    } catch {
      return null
    }
  }
  const set = (key, value) => {
    try {
      storage?.setItem(key, value)
    } catch {
      /* pins hold for this page */
    }
  }
  const read = (workspace) => {
    try {
      const value = JSON.parse(get(`${KEY}:${workspace}`) || '[]')
      return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []
    } catch {
      return []
    }
  }

  const pins = ref([])
  let save = null
  let loading = false
  let workspace = ''
  let serverList = []

  watch(pins, (value) => {
    if (!workspace) return
    set(`${KEY}:${workspace}`, JSON.stringify(value))
    if (save && !loading && !same(value, serverList)) {
      save(value).catch(() => { /* kept in this browser; saved again on the next change */ })
    }
  }, { deep: true })

  function togglePin(name) {
    if (!name) return
    pins.value = pins.value.includes(name) ? pins.value.filter((key) => key !== name) : [name, ...pins.value]
  }

  // key: the workspace these pins belong to; fetcher(path, {method, body}) -> parsed data (api.js `api`).
  async function loadPins(key, fetcher) {
    workspace = key
    save = (list) => fetcher('/api/workspace/pins', { method: 'PUT', body: { pins: list } })
    serverList = []
    loading = true
    // Show only this workspace's cache while the server answers; a previous
    // workspace's pins must never survive a switch.
    pins.value = read(key)
    try {
      const stored = await fetcher('/api/workspace/pins')
      const marker = get(`${IMPORTED}:${key}`)
      let next
      if (!stored.pins.length && !marker && read(key).length) {
        next = (await save(read(key))).pins
      } else {
        next = stored.pins
      }
      serverList = next
      pins.value = next
      set(`${IMPORTED}:${key}`, '1')
    } finally {
      loading = false
    }
  }

  return { pins, togglePin, loadPins }
}

export const { pins, togglePin, loadPins } = createPinStore(globalThis.localStorage)
