<template>
  <div class="ws-inbox" :class="{ reading: !!current }">
    <section class="ws-inbox-list" aria-label="Conversations">
      <header class="ws-inbox-head">
        <div>
          <h1>Inbox</h1>
          <p>{{ items.length }} item{{ items.length === 1 ? '' : 's' }} · chats are kept in this browser</p>
        </div>
      </header>
      <label class="ws-inbox-search">
        <Ico name="search" />
        <input v-model="q" type="search" placeholder="Search chats and reports" aria-label="Search the inbox" />
      </label>
      <div class="ws-seg" role="tablist" aria-label="Filter the inbox">
        <button
          v-for="f in filters"
          :key="f.id"
          type="button"
          role="tab"
          :aria-selected="filter === f.id"
          @click="filter = f.id"
        >
          <Ico :name="f.icon" :size="14" />{{ f.label }}<span class="ws-seg-n">{{ f.n }}</span>
        </button>
      </div>
      <ul class="ws-inbox-items" role="listbox" aria-label="Inbox items" tabindex="0" :aria-activedescendant="current ? `ws-in-${current.key}` : undefined" @keydown="onKey">
        <template v-for="g in grouped" :key="g.name">
          <li class="ws-inbox-day" role="presentation">{{ g.name }}</li>
          <li
            v-for="it in g.items"
            :id="`ws-in-${it.key}`"
            :key="it.key"
            role="option"
            :aria-selected="current?.key === it.key"
            :class="{ active: current?.key === it.key }"
            @click="select(it)"
          >
            <span class="ws-inbox-avatar" :class="it.type === 'report' ? 'report' : it.agent"><Ico :name="it.type === 'report' ? 'file' : agentById(it.agent).icon" /></span>
            <span class="ws-inbox-body">
              <span class="ws-inbox-top">
                <b>{{ it.title }}</b>
                <time>{{ timeAgo(it.at) }}</time>
              </span>
              <span class="ws-inbox-preview">{{ it.type === 'report' ? it.line : `${it.who}: ${it.last}` }}</span>
              <span class="ws-inbox-tags">
                <span v-if="it.type === 'report'" class="ws-tagx accent"><Ico name="done" :size="12" />Report ready</span>
                <span v-for="a in it.agents || []" :key="a" class="ws-tagx"><Ico :name="agentById(a).icon" :size="12" />{{ agentById(a).label }}</span>
                <span v-if="it.count" class="ws-tagx muted">{{ it.count }} messages</span>
                <span v-if="isPinned(it)" class="ws-tagx muted"><Ico name="pin" :size="12" />Pinned</span>
              </span>
            </span>
          </li>
        </template>
        <li v-if="!shown.length" class="ws-inbox-none">
          <Ico name="inbox" :size="28" />
          <b>{{ items.length ? 'Nothing matches' : 'No chats yet' }}</b>
          <span>{{ items.length ? 'Try another word or filter.' : 'Open a run and ask a question; the chat shows up here.' }}</span>
        </li>
      </ul>
    </section>

    <section class="ws-inbox-read" aria-label="Selected conversation" aria-live="polite">
      <template v-if="current">
        <header class="ws-read-head">
          <button type="button" class="ws-icon-btn ws-back" aria-label="Back to the list" @click="current = null"><Ico name="right" style="transform: rotate(180deg)" /></button>
          <div class="ws-read-title">
            <h2>{{ current.title }}</h2>
            <p>
              <span v-if="current.decision" class="pill" :class="String(current.decision).toLowerCase()">{{ String(current.decision).toUpperCase() }}</span>
              <span class="pill sim">Simulated</span>
              <span v-if="current.at">{{ new Date(current.at).toLocaleString() }}</span>
            </p>
          </div>
          <div class="ws-read-actions">
            <button type="button" class="ws-icon-btn" :aria-pressed="isPinned(current)" :title="isPinned(current) ? 'Unpin run' : 'Pin run to the sidebar'" @click="togglePin(current.pin)">
              <Ico :name="isPinned(current) ? 'unpin' : 'pin'" />
            </button>
            <button v-if="current.type === 'chat'" type="button" class="ws-icon-btn" title="Download the chat as Markdown" @click="exportChat(current.title, current.messages)"><Ico name="download" /></button>
            <button v-if="current.type === 'chat'" type="button" class="ws-icon-btn danger" title="Delete this chat from this browser" @click="remove(current)"><Ico name="trash" /></button>
            <RouterLink class="ws-btn primary" :to="current.to"><Ico name="external" :size="14" />Open run</RouterLink>
          </div>
        </header>
        <div v-if="current.type === 'chat'" class="ws-read-thread">
          <div v-for="(m, i) in current.messages" :key="i" class="ws-read-msg" :class="{ me: m.role === 'user' }">
            <span class="ws-read-av" :class="m.role === 'user' ? 'me' : m.agent"><Ico :name="m.role === 'user' ? 'user' : agentById(m.agent).icon" :size="14" /></span>
            <div>
              <small>{{ m.role === 'user' ? `You → ${agentById(m.agent).label}` : m.who || 'MarketMirror' }}<span v-if="m.simulated" class="pill sim xs">Simulated</span><time v-if="m.at"> · {{ timeAgo(m.at) }}</time></small>
              <p>{{ m.text }}</p>
              <p v-if="m.chartKey" class="ws-note"><Ico name="chart" :size="12" /> Chart: {{ m.caption }} (open the run to see it)</p>
              <p v-if="m.transcript" class="ws-note"><Ico name="users" :size="12" /> Transcript of {{ m.transcript.length }} turns (open the run to read it)</p>
            </div>
          </div>
        </div>
        <div v-else class="ws-read-report">
          <Ico name="file" :size="26" />
          <p>{{ current.line }}</p>
          <p class="ws-note">The report agent wrote this report from the simulated run. Open the run to read it with the charts, or ask the report agent a follow-up question.</p>
        </div>
      </template>
      <div v-else class="ws-read-empty">
        <Ico name="mail" :size="32" />
        <b>Select a conversation</b>
        <span>Use ↑ ↓ in the list, or click an item.</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import Ico from './Ico.vue'
import { agentById, deleteChat, exportChat, pins, timeAgo, togglePin } from '../../workspace/agents.js'

const props = defineProps({ items: { type: Array, default: () => [] }, search: { type: String, default: '' } })
const q = ref(''), filter = ref('all'), current = ref(null)
watch(() => props.search, (v) => (q.value = v), { immediate: true })

const isPinned = (it) => pins.value.includes(it.pin)
const filters = computed(() => [
  { id: 'all', label: 'All', icon: 'inbox', n: props.items.length },
  { id: 'chat', label: 'Chats', icon: 'chats', n: props.items.filter((i) => i.type === 'chat').length },
  { id: 'report', label: 'Reports', icon: 'file', n: props.items.filter((i) => i.type === 'report').length },
  { id: 'pinned', label: 'Pinned', icon: 'pin', n: props.items.filter(isPinned).length }
])
const shown = computed(() => {
  const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return props.items
    .filter((i) => filter.value === 'all' || (filter.value === 'pinned' ? isPinned(i) : i.type === filter.value))
    .filter((i) => words.every((w) => `${i.title} ${i.last || ''} ${i.line || ''}`.toLowerCase().includes(w)))
})
const day = (t) => {
  if (!t) return 'Earlier'
  const d = new Date(t), now = new Date()
  const diff = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000)
  return diff <= 0 ? 'Today' : diff === 1 ? 'Yesterday' : diff < 7 ? 'This week' : 'Earlier'
}
const grouped = computed(() => {
  const out = []
  for (const it of shown.value) {
    const name = day(it.at)
    let g = out.find((x) => x.name === name)
    if (!g) out.push((g = { name, items: [] }))
    g.items.push(it)
  }
  return out
})
watch(shown, (list) => {
  if (current.value && !list.some((i) => i.key === current.value.key)) current.value = null
})
watch(() => props.items, (list) => {
  if (current.value) current.value = list.find((i) => i.key === current.value.key) || null
})

function select(it) {
  current.value = it
}
function onKey(e) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) || !shown.value.length) return
  e.preventDefault()
  const list = shown.value
  const i = current.value ? list.findIndex((x) => x.key === current.value.key) : -1
  const n = list.length
  const next = e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : e.key === 'ArrowDown' ? Math.min(n - 1, i + 1) : Math.max(0, i - 1)
  current.value = list[next]
  document.getElementById(`ws-in-${list[next].key}`)?.scrollIntoView({ block: 'nearest' })
}
function remove(it) {
  if (!window.confirm(`Delete the chat on “${it.title}” from this browser? This cannot be undone.`)) return
  deleteChat(it.run)
  current.value = null
}
</script>
