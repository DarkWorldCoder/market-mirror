// The workspace's agents: who answers a chat message. Shared by the top-bar tabs, the home chat box and a run's
// chat. "Results" answers from saved files (no model call); the other three call the configured model provider.
import { ref, watch } from 'vue'

export const AGENTS = [
  { id: 'run', label: 'Results', icon: 'chart', paid: false, title: 'Answers from the saved files with a chart. No model call.',
    text: 'Answers common questions (audience, objections, ads, intent, people, decision) from the saved results, with a chart.' },
  { id: 'report', label: 'Report agent', icon: 'sparkles', paid: true, title: 'One or more model calls to your provider',
    text: 'The ReportAgent reads the run and its market map and answers in plain language. Needs the simulation on this backend.' },
  { id: 'person', label: 'Person', icon: 'user', paid: true, title: 'One model call to your provider',
    text: 'Talk to one simulated person, with their decision card and memories of the run. The reply is written by a model playing an invented person.' },
  { id: 'focus', label: 'Focus group', icon: 'users', paid: true, title: 'About 4 model calls per person per question',
    text: 'Each line you send is one discussion question. Private verdict, moderated discussion, private verdict again, with a conformity check.' }
]

const read = (key, fallback) => {
  try {
    return localStorage.getItem(key) || fallback
  } catch {
    return fallback
  }
}

/** The agent the next message goes to; remembered in this browser. */
export const agent = ref(AGENTS.some((a) => a.id === read('mm-agent', '')) ? read('mm-agent', '') : 'run')
watch(agent, (v) => {
  try {
    localStorage.setItem('mm-agent', v)
  } catch {
    /* private mode: the choice holds for this page */
  }
})

/** A message typed on the home page, handed to the run page that opens next (never put in the URL). */
export const pending = ref(null)

export const agentById = (id) => AGENTS.find((a) => a.id === id) || AGENTS[0]

/** Saved chats in this browser: one entry per run with its last message, newest first. */
export function savedChats() {
  const out = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key || !key.startsWith('mm-chat-')) continue
      const list = JSON.parse(localStorage.getItem(key) || '[]')
      if (!Array.isArray(list) || !list.length) continue
      const last = list[list.length - 1]
      const agents = [...new Set(list.map((m) => m.agent).filter(Boolean))]
      out.push({ run: key.slice(8), count: list.length, last: String(last.text || '').slice(0, 160), who: last.who || (last.role === 'user' ? 'You' : 'MarketMirror'),
        at: last.at || 0, agent: last.agent || agents[agents.length - 1] || 'run', agents, messages: list })
    }
  } catch {
    /* storage unavailable: no saved chats */
  }
  return out.sort((a, b) => (b.at || 0) - (a.at || 0))
}

/** Runs pinned to the top of the sidebar, remembered in this browser. */
export const pins = ref((() => {
  try {
    return JSON.parse(localStorage.getItem('mm-pins') || '[]')
  } catch {
    return []
  }
})())
watch(pins, (v) => {
  try {
    localStorage.setItem('mm-pins', JSON.stringify(v))
  } catch {
    /* pins hold for this page */
  }
}, { deep: true })
export function togglePin(key) {
  pins.value = pins.value.includes(key) ? pins.value.filter((k) => k !== key) : [key, ...pins.value]
}

/** Forget one run's chat in this browser. */
export function deleteChat(run) {
  try {
    localStorage.removeItem(`mm-chat-${run}`)
    window.dispatchEvent(new Event('mm-chat-saved'))
  } catch {
    /* nothing stored */
  }
}

/** A chat as Markdown, every answer marked simulated, downloaded as a file. */
export function exportChat(title, messages) {
  const lines = [`# ${title}`, '', '_Simulated people, not real buyers. Check decisions with real people before you spend._', '']
  for (const m of messages || []) {
    const when = m.at ? new Date(m.at).toLocaleString() : ''
    const who = m.role === 'user' ? `You → ${agentById(m.agent).label}` : `${m.who || 'MarketMirror'}${m.simulated ? ' (simulated)' : ''}`
    lines.push(`**${who}**${when ? ` · ${when}` : ''}`, '', String(m.text || ''), '')
    for (const t of m.transcript || []) lines.push(`> ${t.speaker}${t.segment ? ` (${t.segment})` : ''}: ${t.text}`)
    if (m.transcript?.length) lines.push('')
  }
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: `${String(title).replace(/[^\w-]+/g, '_').slice(0, 60) || 'chat'}.md` })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

/** "3 min ago", "yesterday", "12 Oct". */
export function timeAgo(t) {
  if (!t) return ''
  const s = (Date.now() - new Date(t).getTime()) / 1000
  if (!Number.isFinite(s)) return ''
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 172800) return 'yesterday'
  return new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
