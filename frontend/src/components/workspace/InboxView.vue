<template>
  <div class="inbox" :class="{ reading: !!current }">
    <section class="inbox-list" aria-label="Conversations and reports">
      <header class="inbox-head">
        <h1>Inbox</h1>
        <p>{{ items.length }} {{ items.length === 1 ? 'item' : 'items' }} · chats saved in this browser and finished reports</p>
      </header>
      <label class="inbox-search"><Search :size="16" aria-hidden="true" /><input v-model="q" type="search" placeholder="Search chats and reports" aria-label="Search the inbox" /></label>
      <div class="inbox-filters" role="tablist" aria-label="Filter the inbox">
        <button v-for="f in filters" :key="f.id" type="button" role="tab" :aria-selected="filter === f.id" @click="filter = f.id">
          <component :is="f.icon" :size="14" aria-hidden="true" />{{ f.label }}<span>{{ f.n }}</span>
        </button>
      </div>
      <ul class="inbox-items" role="listbox" aria-label="Inbox items" tabindex="0" :aria-activedescendant="current ? `in-${current.key}` : undefined" @keydown="onKey">
        <template v-for="g in grouped" :key="g.name">
          <li class="inbox-day" role="presentation">{{ g.name }}</li>
          <li v-for="it in g.items" :id="`in-${it.key}`" :key="it.key" role="option" :aria-selected="current?.key === it.key" :class="{ active: current?.key === it.key }" @click="current = it">
            <span class="inbox-avatar" :class="it.type"><component :is="it.type === 'report' ? FileText : MessageSquare" :size="16" aria-hidden="true" /></span>
            <span class="inbox-body">
              <span class="inbox-top"><b>{{ it.title }}</b><time>{{ ago(it.at) }}</time></span>
              <span class="inbox-preview">{{ it.preview }}</span>
              <span class="inbox-tags">
                <span v-if="it.type === 'report'" class="inbox-tag ok"><CircleCheck :size="12" aria-hidden="true" />Report ready</span>
                <span v-if="it.runTitle" class="inbox-tag"><ChartNoAxesCombined :size="12" aria-hidden="true" />{{ it.runTitle }}</span>
                <span v-if="it.count" class="inbox-tag">{{ it.count }} messages</span>
                <span v-if="isPinned(it)" class="inbox-tag"><Pin :size="12" aria-hidden="true" />Pinned run</span>
              </span>
            </span>
          </li>
        </template>
        <li v-if="!shown.length" class="inbox-none">
          <InboxIcon :size="28" aria-hidden="true" />
          <b>{{ items.length ? 'Nothing matches' : 'No chats yet' }}</b>
          <span>{{ items.length ? 'Try another word or filter.' : 'Start a chat; it shows up here.' }}</span>
        </li>
      </ul>
    </section>

    <section class="inbox-read" aria-label="Selected item" aria-live="polite">
      <template v-if="current">
        <header class="read-head">
          <button type="button" class="read-back" aria-label="Back to the list" @click="current = null"><ArrowLeft :size="16" /></button>
          <div class="read-title">
            <h2>{{ current.title }}</h2>
            <p><span class="inbox-tag sim">Simulated</span><span v-if="current.at">{{ new Date(current.at).toLocaleString() }}</span></p>
          </div>
          <div class="read-actions">
            <button v-if="current.run" type="button" :aria-pressed="isPinned(current)" :title="isPinned(current) ? 'Unpin run' : 'Pin run to the sidebar'" :aria-label="isPinned(current) ? 'Unpin run' : 'Pin run'" @click="togglePin(current.run)"><component :is="isPinned(current) ? PinOff : Pin" :size="16" /></button>
            <button v-if="current.type === 'chat'" type="button" title="Download as Markdown" aria-label="Download as Markdown" @click="exportChat(current)"><Download :size="16" /></button>
            <button v-if="current.type === 'chat'" type="button" class="danger" title="Delete this chat" aria-label="Delete this chat" @click="remove(current)"><Trash2 :size="16" /></button>
            <RouterLink class="read-open" :to="current.to"><ArrowUpRight :size="15" aria-hidden="true" />{{ current.type === 'chat' ? 'Open chat' : 'Open report' }}</RouterLink>
          </div>
        </header>
        <div v-if="current.type === 'chat'" class="read-thread">
          <article v-for="(m, i) in current.messages" :key="m.id || i" class="read-msg" :class="m.role">
            <span class="read-av" aria-hidden="true"><component :is="m.role === 'user' ? UserRound : Sparkles" :size="14" /></span>
            <div>
              <small>{{ m.role === 'user' ? 'You' : 'MarketMirror' }}</small>
              <p v-if="m.role === 'user'">{{ m.content }}</p>
              <MarkdownText v-else :text="String(m.content || '')" />
              <p v-if="extras(m)" class="read-note">{{ extras(m) }} (open the chat to see it)</p>
            </div>
          </article>
        </div>
        <div v-else class="read-report">
          <FileText :size="26" aria-hidden="true" />
          <p>{{ current.preview }}</p>
          <p class="read-note">The report agent wrote this from a simulated run. Open it to see the charts and ask follow-up questions.</p>
        </div>
      </template>
      <div v-else class="read-empty">
        <Mail :size="32" aria-hidden="true" />
        <b>Select a conversation</b>
        <span>Use ↑ ↓ in the list, or click an item.</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowLeft, ArrowUpRight, ChartNoAxesCombined, CircleCheck, Download, FileText, Inbox as InboxIcon, Mail, MessageSquare, Pin, PinOff, Search, Sparkles, Trash2, UserRound } from 'lucide-vue-next'
import MarkdownText from './MarkdownText.vue'
import { api, token } from '../../workspace/api'
import { pins, togglePin } from '../../workspace/pins'

const props = defineProps({ runs: { type: Array, default: () => [] } })
const STORE = 'mm-conversations-v1'
const chats = ref([]), reports = ref([]), q = ref(''), filter = ref('all'), current = ref(null)

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(STORE) || '[]')
    chats.value = Array.isArray(v) ? v : []
  } catch {
    chats.value = []
  }
}
const runTitle = (name) => props.runs.find((r) => r.name === name)?.title || name
const items = computed(() => {
  const out = chats.value.filter((c) => Array.isArray(c.messages) && c.messages.length).map((c) => {
    const last = [...c.messages].reverse().find((m) => m.content) || {}
    return {
      key: `c-${c.id}`, type: 'chat', id: c.id, title: c.title || 'New chat', at: c.updated || 0, run: c.run || null, runTitle: c.run ? runTitle(c.run) : '',
      preview: `${last.role === 'user' ? 'You' : 'MarketMirror'}: ${String(last.content || '').slice(0, 160)}`, count: c.messages.length, messages: c.messages,
      to: { path: '/', query: { chat: c.id, ...(c.project ? { project: c.project } : {}) } }
    }
  })
  for (const r of reports.value) {
    if (r.status !== 'completed') continue
    const run = props.runs.find((x) => x.simulation_id === r.simulation_id)
    if (!run) continue
    out.push({ key: `r-${r.report_id}`, type: 'report', title: r.outline?.title || run.title, at: r.completed_at || r.created_at, run: run.name, runTitle: run.title,
      preview: r.outline?.summary || `Report on ${run.title}`, to: { path: '/', query: { run: run.name, show: 'reports' } } })
  }
  return out.sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0))
})
const isPinned = (it) => !!it.run && pins.value.includes(it.run)
const filters = computed(() => [
  { id: 'all', label: 'All', icon: InboxIcon, n: items.value.length },
  { id: 'chat', label: 'Chats', icon: MessageSquare, n: items.value.filter((i) => i.type === 'chat').length },
  { id: 'report', label: 'Reports', icon: FileText, n: items.value.filter((i) => i.type === 'report').length },
  { id: 'pinned', label: 'Pinned', icon: Pin, n: items.value.filter(isPinned).length }
])
const shown = computed(() => {
  const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return items.value
    .filter((i) => filter.value === 'all' || (filter.value === 'pinned' ? isPinned(i) : i.type === filter.value))
    .filter((i) => words.every((w) => `${i.title} ${i.preview} ${i.runTitle}`.toLowerCase().includes(w)))
})
const day = (t) => {
  if (!t) return 'Earlier'
  const diff = Math.floor((new Date(new Date().toDateString()) - new Date(new Date(t).toDateString())) / 86400000)
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
watch(items, (list) => {
  if (current.value) current.value = list.find((i) => i.key === current.value.key) || null
})

function ago(t) {
  if (!t) return ''
  const s = (Date.now() - new Date(t).getTime()) / 1000
  if (!Number.isFinite(s)) return ''
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 172800) return 'yesterday'
  return new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
function extras(m) {
  const parts = []
  if (m.artifacts?.length) parts.push(`${m.artifacts.length} chart${m.artifacts.length === 1 ? '' : 's'}`)
  if (m.reportBrowser) parts.push('a report browser')
  if (m.audience_run) parts.push('an audience view')
  if (m.browser_observations?.length) parts.push('a page capture')
  return parts.join(', ')
}
function onKey(e) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) || !shown.value.length) return
  e.preventDefault()
  const list = shown.value, n = list.length
  const i = current.value ? list.findIndex((x) => x.key === current.value.key) : -1
  const next = e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : e.key === 'ArrowDown' ? Math.min(n - 1, i + 1) : Math.max(0, i - 1)
  current.value = list[next]
  document.getElementById(`in-${list[next].key}`)?.scrollIntoView({ block: 'nearest' })
}
function exportChat(it) {
  const lines = [`# ${it.title}`, '', '_Simulated people, not real buyers. Check decisions with real people before you spend._', '']
  for (const m of it.messages) lines.push(`**${m.role === 'user' ? 'You' : 'MarketMirror'}**`, '', String(m.content || ''), '')
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: `${String(it.title).replace(/[^\w-]+/g, '_').slice(0, 60) || 'chat'}.md` })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
function remove(it) {
  if (!window.confirm(`Delete “${it.title}” from this browser? This cannot be undone.`)) return
  try {
    localStorage.setItem(STORE, JSON.stringify(chats.value.filter((c) => c.id !== it.id)))
    window.dispatchEvent(new Event('mm-chats-updated'))
  } catch {
    /* storage unavailable */
  }
  load()
  current.value = null
}

onMounted(async () => {
  load()
  window.addEventListener('mm-chats-updated', load)
  if (!token()) return
  try {
    const list = await api('/api/report/list?limit=100')
    reports.value = Array.isArray(list) ? list : []
  } catch {
    reports.value = []
  }
})
onBeforeUnmount(() => window.removeEventListener('mm-chats-updated', load))
</script>

<style scoped>
.inbox { display: grid; grid-template-columns: minmax(300px, 380px) minmax(0, 1fr); min-height: calc(100dvh - 120px); }
.inbox-list { border-right: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; padding: 22px 14px 0; }
.inbox-head h1 { font-size: 22px; font-weight: 650; letter-spacing: -0.3px; }
.inbox-head p { color: var(--muted); font-size: 12.5px; margin-top: 3px; }
.inbox-search { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 10px; padding: 8px 11px; background: var(--panel); margin: 14px 0 10px; color: var(--muted); }
.inbox-search:focus-within { border-color: var(--accent); }
.inbox-search input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; font-size: 13px; color: var(--text); }
.inbox-filters { display: flex; gap: 2px; padding: 3px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-2); overflow-x: auto; }
.inbox-filters button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: none; border-radius: 7px; padding: 6px 10px; font-size: 12.5px; color: var(--muted); cursor: pointer; white-space: nowrap; }
.inbox-filters button span { font-size: 11px; opacity: 0.75; }
.inbox-filters button[aria-selected='true'] { background: var(--panel); color: var(--text); box-shadow: var(--shadow); }
.inbox-items { list-style: none; margin: 10px -4px 0; padding: 0 0 16px; overflow-y: auto; flex: 1; min-height: 0; outline: none; }
.inbox-items:focus-visible { box-shadow: inset 0 0 0 2px var(--accent); border-radius: 10px; }
.inbox-day { font-size: 10.5px; font-weight: 650; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); padding: 12px 10px 6px; }
.inbox-items li[role='option'] { display: flex; gap: 11px; padding: 11px 10px; border-radius: 11px; cursor: pointer; border: 1px solid transparent; }
.inbox-items li[role='option']:hover { background: var(--panel-2); }
.inbox-items li.active { background: var(--accent-2); border-color: color-mix(in srgb, var(--accent) 35%, transparent); }
.inbox-avatar, .read-av { width: 34px; height: 34px; flex: none; border-radius: 10px; display: grid; place-items: center; background: var(--accent-2); color: var(--accent); }
.inbox-avatar.report { background: color-mix(in srgb, var(--yes) 15%, transparent); color: var(--yes); }
.inbox-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.inbox-top { display: flex; gap: 8px; align-items: baseline; }
.inbox-top b { flex: 1; min-width: 0; font-size: 13.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.inbox-top time { font-size: 11px; color: var(--muted); flex: none; }
.inbox-preview { font-size: 12.5px; color: var(--muted); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.4; }
.inbox-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
.inbox-tag { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; border: 1px solid var(--line); border-radius: 999px; padding: 1px 8px; color: var(--muted); white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.inbox-tag.ok { color: var(--yes); border-color: color-mix(in srgb, var(--yes) 45%, var(--line)); }
.inbox-tag.sim { color: var(--warm); border-color: color-mix(in srgb, var(--warm) 45%, var(--line)); }
.inbox-none, .read-empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px; color: var(--muted); padding: 48px 20px; font-size: 12.5px; }
.inbox-none b, .read-empty b { color: var(--text); font-size: 14px; }
.read-empty { height: 100%; justify-content: center; }
.inbox-read { min-width: 0; display: flex; flex-direction: column; }
.read-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 18px 22px; border-bottom: 1px solid var(--line); }
.read-back { display: none; }
.read-title { flex: 1; min-width: 200px; }
.read-title h2 { font-size: 16px; font-weight: 650; }
.read-title p { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; color: var(--muted); }
.read-actions { display: flex; align-items: center; gap: 4px; }
.read-actions button, .read-back { display: inline-grid; place-items: center; width: 32px; height: 32px; border: 1px solid transparent; border-radius: 9px; background: none; color: var(--muted); cursor: pointer; }
.read-actions button:hover, .read-back:hover { background: var(--panel-2); color: var(--text); }
.read-actions button[aria-pressed='true'] { color: var(--accent); background: var(--accent-2); }
.read-actions button.danger:hover { color: var(--no); background: color-mix(in srgb, var(--no) 12%, transparent); }
.read-open { display: inline-flex; align-items: center; gap: 6px; margin-left: 6px; padding: 7px 12px; border-radius: 9px; background: var(--text); color: var(--panel); font-size: 13px; font-weight: 550; text-decoration: none; }
.read-thread { overflow-y: auto; padding: 18px 22px 30px; display: flex; flex-direction: column; gap: 16px; }
.read-msg { display: flex; gap: 10px; max-width: 780px; }
.read-msg small { color: var(--muted); font-size: 11.5px; }
.read-msg p { font-size: 13.5px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; margin-top: 2px; }
.read-msg .read-av { width: 28px; height: 28px; border-radius: 8px; }
.read-msg.user .read-av { background: var(--panel-2); color: var(--muted); border: 1px solid var(--line); }
.read-note { font-size: 12px !important; color: var(--muted); }
.read-report { padding: 28px 22px; max-width: 680px; display: flex; flex-direction: column; gap: 10px; font-size: 14px; line-height: 1.6; color: var(--text); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 900px) {
  .inbox { grid-template-columns: 1fr; }
  .inbox-list { border-right: 0; }
  .inbox-read { display: none; }
  .inbox.reading .inbox-list { display: none; }
  .inbox.reading .inbox-read { display: flex; }
  .read-back { display: inline-grid; }
}
</style>
