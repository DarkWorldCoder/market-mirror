<template>
  <div v-if="open" class="ws-modal-back" @mousedown.self="close">
    <div class="ws-palette" role="dialog" aria-modal="true" aria-label="Search or jump to" @keydown="onKey">
      <div class="ws-palette-search">
        <Ico name="search" :size="18" />
        <input
          ref="box"
          v-model="q"
          type="text"
          placeholder="Search runs, pages, agents and actions…"
          aria-label="Search runs, pages, agents and actions"
          role="combobox"
          aria-expanded="true"
          aria-controls="ws-palette-list"
          :aria-activedescendant="shown.length ? `ws-pal-${active}` : undefined"
        />
        <kbd>Esc</kbd>
      </div>
      <ul id="ws-palette-list" class="ws-palette-list" role="listbox" aria-label="Results">
        <template v-for="(g, gi) in groups" :key="g.name">
          <li class="ws-palette-group" role="presentation">{{ g.name }}</li>
          <li
            v-for="it in g.items"
            :id="`ws-pal-${it.i}`"
            :key="it.id"
            role="option"
            :aria-selected="it.i === active"
            :class="{ active: it.i === active }"
            @mousemove="active = it.i"
            @click="pick(it)"
          >
            <span class="ws-palette-ico"><Ico :name="it.icon || 'right'" /></span>
            <span class="ws-palette-label">{{ it.label }}</span>
            <small v-if="it.hint">{{ it.hint }}</small>
            <span v-if="gi === 0 && it.i === active" class="ws-palette-enter" aria-hidden="true"><Ico name="enter" :size="14" /></span>
          </li>
        </template>
        <li v-if="!shown.length" class="ws-palette-empty">Nothing matches “{{ q }}”.</li>
      </ul>
      <footer class="ws-palette-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></footer>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import Ico from './Ico.vue'

const props = defineProps({ open: Boolean, items: { type: Array, default: () => [] } })
const emit = defineEmits(['close'])
const q = ref(''), active = ref(0), box = ref(null)
let lastFocus = null

const shown = computed(() => {
  const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return props.items.filter((it) => words.every((w) => `${it.label} ${it.hint || ''} ${it.group}`.toLowerCase().includes(w))).slice(0, 40)
})
const groups = computed(() => {
  const out = []
  shown.value.forEach((it, i) => {
    let g = out.find((x) => x.name === it.group)
    if (!g) out.push((g = { name: it.group, items: [] }))
    g.items.push({ ...it, i })
  })
  // keep the visual order and the arrow-key order the same
  let n = 0
  for (const g of out) for (const it of g.items) it.i = n++
  return out
})
const flat = computed(() => groups.value.flatMap((g) => g.items))

watch(() => props.open, async (v) => {
  if (v) {
    lastFocus = document.activeElement
    q.value = ''
    active.value = 0
    await nextTick()
    box.value?.focus()
  } else if (lastFocus && lastFocus.focus) {
    lastFocus.focus()
  }
})
watch(q, () => (active.value = 0))

function close() {
  emit('close')
}
function pick(it) {
  close()
  it.run && it.run()
}
function onKey(e) {
  const n = flat.value.length
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  } else if (e.key === 'ArrowDown' && n) {
    e.preventDefault()
    active.value = (active.value + 1) % n
  } else if (e.key === 'ArrowUp' && n) {
    e.preventDefault()
    active.value = (active.value + n - 1) % n
  } else if (e.key === 'Enter' && n) {
    e.preventDefault()
    pick(flat.value[active.value])
  } else if (e.key === 'Tab') {
    e.preventDefault() // focus stays in the dialog
    box.value?.focus()
  }
  if (['ArrowDown', 'ArrowUp'].includes(e.key)) nextTick(() => document.getElementById(`ws-pal-${active.value}`)?.scrollIntoView({ block: 'nearest' }))
}
</script>
