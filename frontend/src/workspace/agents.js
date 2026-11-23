// The workspace's agents: who answers a chat message. Shared by the top-bar tabs, the home chat box and a run's
// chat. "Results" answers from saved files (no model call); the other three call the configured model provider.
import { ref, watch } from 'vue'

export const AGENTS = [
  { id: 'run', label: 'Results', icon: '▦', paid: false, title: 'Answers from the saved files with a chart. No model call.',
    text: 'Answers common questions (audience, objections, ads, intent, people, decision) from the saved results, with a chart.' },
  { id: 'report', label: 'Report agent', icon: '✦', paid: true, title: 'One or more model calls to your provider',
    text: 'The ReportAgent reads the run and its market map and answers in plain language. Needs the simulation on this backend.' },
  { id: 'person', label: 'Person', icon: '☺', paid: true, title: 'One model call to your provider',
    text: 'Talk to one simulated person, with their decision card and memories of the run. The reply is written by a model playing an invented person.' },
  { id: 'focus', label: 'Focus group', icon: '◎', paid: true, title: 'About 4 model calls per person per question',
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
      out.push({ run: key.slice(8), count: list.length, last: String(last.text || '').slice(0, 160), who: last.who || (last.role === 'user' ? 'You' : 'MarketMirror'), at: last.at || 0 })
    }
  } catch {
    /* storage unavailable: no saved chats */
  }
  return out.sort((a, b) => (b.at || 0) - (a.at || 0))
}
