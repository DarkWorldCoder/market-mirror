// Saved runs pinned to the top of the sidebar, remembered in this browser (run folder names).
import { ref, watch } from 'vue'

const KEY = 'mm-pinned-runs'
const read = () => {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}
export const pins = ref(read())
watch(pins, (v) => {
  try {
    localStorage.setItem(KEY, JSON.stringify(v))
  } catch {
    /* pins hold for this page */
  }
}, { deep: true })
export function togglePin(name) {
  if (!name) return
  pins.value = pins.value.includes(name) ? pins.value.filter((k) => k !== name) : [name, ...pins.value]
}
