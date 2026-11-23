<template>
  <div class="ws" :class="{ rail }" :data-theme="theme">
    <a class="ws-skip" href="#ws-canvas">Skip to content</a>
    <nav class="ws-side" :class="{ open: menuOpen }" aria-label="Workspace">
      <details class="ws-switch">
        <summary>
          <i aria-hidden="true"><Ico name="sparkles" :size="15" /></i>
          <span><b>MarketMirror</b><small>Local workspace</small></span>
          <Ico name="down" :size="14" class="ws-caret" />
        </summary>
        <div class="ws-switch-menu">
          <RouterLink to="/workspace"><Ico name="home" :size="15" />Workspace <small>this page</small></RouterLink>
          <RouterLink to="/"><Ico name="layers" :size="15" />Compare two ideas <small>guided app</small></RouterLink>
          <a :href="settingsLink"><Ico name="settings" :size="15" />Model settings <small>provider and keys</small></a>
        </div>
      </details>
      <button type="button" class="ws-search" aria-label="Search or jump to (Ctrl K)" @click="paletteOpen = true">
        <Ico name="search" :size="15" />
        <span>Search or jump to…</span>
        <kbd aria-hidden="true">{{ modKey }}K</kbd>
      </button>
      <div class="ws-nav">
        <RouterLink v-for="n in nav" :key="n.id" :to="n.to" :class="{ active: view === n.id }" :title="rail ? n.label : undefined" :aria-current="view === n.id ? 'page' : undefined" @click="menuOpen = false">
          <Ico :name="n.icon" :size="16" />{{ n.label }}
          <span v-if="n.id === 'inbox' && inboxItems.length" class="ws-count" :aria-label="`${inboxItems.length} items`">{{ inboxItems.length }}</span>
        </RouterLink>
      </div>

      <template v-if="pinnedRuns.length">
        <p class="ws-group" id="ws-pins-label"><Ico name="pin" :size="12" />Pinned</p>
        <div class="ws-history" aria-labelledby="ws-pins-label">
          <RunLink v-for="r in pinnedRuns" :key="r.key" :item="r" />
        </div>
      </template>
      <p class="ws-group" id="ws-runs-label"><Ico name="folder" :size="12" />Runs<span class="ws-group-n">{{ runs.length }}</span></p>
      <div class="ws-history" aria-labelledby="ws-runs-label">
        <RunLink v-for="r in recentRuns" :key="r.key" :item="r" />
        <p v-if="!recentRuns.length && !pinnedRuns.length" class="ws-note" style="padding-left: 10px">{{ runsNote }}</p>
      </div>

      <div class="ws-foot">
        <div class="ws-me">
          <span class="ws-avatar" aria-hidden="true">{{ initials }}</span>
          <div><b>You</b><span>{{ providerLine }}</span></div>
          <button type="button" class="ws-icon-btn" :aria-label="theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'" :title="theme === 'dark' ? 'Light mode' : 'Dark mode'" @click="toggleTheme">
            <Ico :name="theme === 'dark' ? 'sun' : 'moon'" />
          </button>
          <button type="button" class="ws-icon-btn" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" @click="keysOpen = true">
            <Ico name="keyboard" />
          </button>
        </div>
      </div>
    </nav>
    <div v-if="menuOpen" class="ws-scrim" aria-hidden="true" @click="menuOpen = false"></div>

    <main class="ws-main">
      <header class="ws-top">
        <button type="button" class="ws-icon-btn ws-menu-btn" :aria-expanded="menuOpen" aria-label="Open menu" @click="menuOpen = !menuOpen"><Ico name="menu" /></button>
        <button type="button" class="ws-icon-btn ws-rail-btn" :aria-pressed="rail" :aria-label="rail ? 'Expand the sidebar' : 'Collapse the sidebar'" :title="`${rail ? 'Expand' : 'Collapse'} the sidebar (${modKey}B)`" @click="toggleRail"><Ico :name="rail ? 'expand' : 'collapse'" /></button>
        <div class="ws-agents" role="group" aria-label="Who answers your messages">
          <button
            v-for="(a, i) in AGENTS"
            :key="a.id"
            type="button"
            class="ws-agent-tab"
            :aria-pressed="agent === a.id"
            :title="`${a.title} (Alt ${i + 1})`"
            @click="agent = a.id"
          >
            <Ico :name="a.icon" :size="15" />{{ a.label }}<span v-if="a.paid" class="ws-paid" title="Sends model calls">$</span>
          </button>
          <RouterLink class="ws-agent-tab add" to="/workspace/agents" title="Every agent and what it costs"><Ico name="plus" :size="14" />Add agent</RouterLink>
        </div>
        <div class="ws-top-right">
          <a class="ws-icon-btn bordered" :href="settingsLink" title="Model settings" aria-label="Model settings"><Ico name="settings" /></a>
          <RouterLink class="ws-btn primary" to="/workspace"><Ico name="plus" :size="15" /><span class="ws-hide-sm">New chat</span></RouterLink>
        </div>
      </header>
      <p v-if="!hasToken" class="ws-error" role="alert">
        Open this workspace with <code>./mm app</code> so it can reach your local runs. The page needs the local session
        it starts.
      </p>
      <p v-else-if="error" class="ws-error" role="alert">{{ error }} <button type="button" class="ws-link" @click="error = ''">Dismiss</button></p>

      <section id="ws-canvas" class="ws-canvas" tabindex="-1">
        <RunView v-if="view === 'run'" :key="'r' + route.params.run" :name="route.params.run" :theme="theme" :provider="provider" />
        <RunView v-else-if="view === 'sim'" :key="'s' + route.params.sim" :sim="route.params.sim" :theme="theme" :provider="provider" />

        <template v-else-if="view === 'home'">
          <div class="ws-hero">
            <div class="ws-orb" aria-hidden="true"></div>
            <h1>{{ greeting }}</h1>
            <h2>What do you want to know about your buyers?</h2>
            <div class="ws-composer big">
              <label class="sr-only" for="ws-home">Message to {{ agentById(agent).label }}</label>
              <div v-if="attachment" class="ws-attached">
                <Ico name="file" :size="14" /><span>{{ attachment.name }} · {{ Math.round(attachment.text.length / 100) / 10 }}k characters</span>
                <button type="button" aria-label="Remove attachment" @click="attachment = null"><Ico name="x" :size="14" /></button>
              </div>
              <textarea id="ws-home" ref="homeBox" v-model="idea" rows="3" :placeholder="homePlaceholder" @keydown="onHomeKey"></textarea>
              <div class="ws-composer-row">
                <button type="button" class="ws-icon-btn" aria-label="Attach a text file" title="Attach a text, Markdown or CSV file (up to 60 KB)" @click="fileInput.click()"><Ico name="attach" /></button>
                <input ref="fileInput" type="file" accept=".txt,.md,.csv,.json" class="sr-only" tabindex="-1" @change="onAttach" />
                <div class="ws-mention">
                  <button type="button" class="ws-chip" :aria-expanded="mentionOpen" aria-haspopup="listbox" title="Pick the run to talk about (or type @)" @click="mentionOpen = !mentionOpen">
                    <Ico name="at" :size="14" /><span class="ws-ell">{{ target ? target.title : 'Pick a run' }}</span><Ico name="down" :size="12" />
                  </button>
                  <div v-if="mentionOpen" class="ws-pop ws-mention-list" role="listbox" aria-label="Runs" @keydown.esc="mentionOpen = false">
                    <input v-model="mentionQ" class="ws-pop-search" type="search" placeholder="Filter runs" aria-label="Filter runs" @keydown.enter.prevent="mentionRuns[0] && pickTarget(mentionRuns[0])" />
                    <button v-for="r in mentionRuns" :key="r.key" type="button" role="option" :aria-selected="target?.key === r.key" @click="pickTarget(r)">
                      <Ico :name="r.kind === 'sim' ? 'activity' : 'folder'" :size="14" />
                      <span>{{ r.title }}<small class="ws-pop-sub">{{ r.name }}</small></span><small>{{ r.people ? Number(r.people).toLocaleString() + ' people' : r.kind === 'sim' ? 'simulation' : 'run' }}</small>
                      <Ico v-if="target?.key === r.key" name="check" :size="14" />
                    </button>
                    <p v-if="!mentionRuns.length">{{ allTargets.length ? 'No run matches.' : runsNote }}</p>
                  </div>
                </div>
                <RouterLink class="ws-chip" to="/workspace/skills"><Ico name="zap" :size="14" />Skills</RouterLink>
                <a class="ws-chip" :href="settingsLink" :title="provider.configured ? 'Model used for paid agents' : 'Connect a model provider'"><Ico name="cpu" :size="14" /><span class="ws-ell">{{ modelName }}</span></a>
                <div class="ws-composer-end">
                  <span class="ws-composer-to"><Ico :name="agentById(agent).icon" :size="14" />{{ agentById(agent).label }}</span>
                  <button type="button" class="ws-send" :disabled="!idea.trim()" :aria-label="`Send to ${agentById(agent).label}`" @click="sendHome"><Ico name="send" :size="17" :stroke="2.2" /></button>
                </div>
              </div>
            </div>
            <p class="ws-note ws-cost" aria-live="polite">
              <Ico :name="agentById(agent).paid ? 'dollar' : 'shield'" :size="12" />
              <b>{{ agentById(agent).label }}</b>
              {{ agentById(agent).paid ? 'sends model calls to your provider when you press send. Answers are simulated.' : 'answers from saved results. No model call.' }}
            </p>
            <div class="ws-quick" aria-label="Quick actions">
              <button v-for="q in quick" :key="q.text" type="button" class="ws-chip" @click="useQuick(q)">
                <Ico :name="q.icon" :size="14" />{{ q.label }}<span v-if="agentById(q.agent).paid" class="ws-paid">$</span>
              </button>
            </div>
            <div v-if="matches.length" class="ws-cards" style="margin-top: 14px" aria-live="polite">
              <component :is="m.to ? 'RouterLink' : 'button'" v-for="m in matches" :key="m.id" class="ws-card" :to="m.to" :style="{ '--tint': m.tint }" @click="m.to ? null : copy(m.command)">
                <span class="ws-ico"><Ico :name="m.icon" /></span><span class="ws-tag">{{ m.tag }}</span>
                <b>{{ m.name }}</b><span>{{ m.to ? m.text : 'Copy: ' + m.command }}</span>
              </component>
            </div>
          </div>

          <div class="ws-section">
            <ul class="ws-glance" aria-label="At a glance">
              <li><Ico name="folder" /><b>{{ runs.length }}</b><span>saved runs</span></li>
              <li><Ico name="users" /><b>{{ totalPeople.toLocaleString() }}</b><span>simulated people</span></li>
              <li><Ico name="chats" /><b>{{ chats.length }}</b><span>chats here</span></li>
              <li><Ico name="file" /><b>{{ readyReports }}</b><span>reports ready</span></li>
            </ul>
            <h3><Ico name="clock" :size="16" />Previous chats <RouterLink to="/workspace/inbox" class="ws-more">View all<Ico name="right" :size="13" /></RouterLink></h3>
            <div class="ws-row" role="list">
              <ChatCard v-for="c in previous.slice(0, 8)" :key="c.key" :item="c" role="listitem" />
            </div>
            <p v-if="!previous.length" class="ws-empty">{{ runsNote }}</p>
            <h3><Ico name="idea" :size="16" />Suggested <RouterLink to="/workspace/skills" class="ws-more">All skills<Ico name="right" :size="13" /></RouterLink></h3>
            <div class="ws-row" role="list">
              <component
                :is="s.to ? 'RouterLink' : 'button'"
                v-for="s in suggested"
                :key="s.id"
                role="listitem"
                class="ws-card"
                :to="s.to"
                :style="{ '--tint': s.tint }"
                @click="s.agent ? useQuick(s) : s.to ? null : copy(s.command)"
              >
                <span class="ws-ico"><Ico :name="s.icon" /></span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b><span>{{ s.text }}</span>
              </component>
            </div>
            <p v-if="copied" class="ws-note" role="status">{{ copied }}</p>
          </div>
        </template>

        <Inbox v-else-if="view === 'inbox'" :items="inboxItems" :search="''" />
        <Compare v-else-if="view === 'compare'" :runs="runs" :theme="theme" />

        <div v-else-if="view === 'agents'" class="ws-section ws-page">
          <header class="ws-page-head"><h1><Ico name="bot" :size="20" />Agents</h1><p>Pick who answers your messages. The tabs at the top do the same; Alt 1 to 4 switch them.</p></header>
          <div class="ws-agent-cards">
            <article v-for="(a, i) in AGENTS" :key="a.id" class="ws-agent-card" :class="{ on: agent === a.id }">
              <span class="ws-agent-ico" :class="a.id"><Ico :name="a.icon" :size="20" /></span>
              <div>
                <h2>{{ a.label }} <span class="ws-tagx" :class="a.paid ? 'warm' : 'accent'">{{ a.paid ? 'Model calls' : 'Free' }}</span></h2>
                <p>{{ a.text }}</p>
                <p class="ws-note">{{ a.title }} · Alt {{ i + 1 }}</p>
              </div>
              <button type="button" class="ws-btn" :class="{ on: agent === a.id }" :aria-pressed="agent === a.id" @click="agent = a.id">
                <Ico :name="agent === a.id ? 'check' : 'play'" :size="14" />{{ agent === a.id ? 'In use' : 'Use' }}
              </button>
            </article>
          </div>
          <h3><Ico name="terminal" :size="16" />More agents <small>Run from your coding agent or the CLI; click to copy</small></h3>
          <div class="ws-cards">
            <button v-for="s in skills.filter((x) => x.command)" :key="s.id" type="button" class="ws-card" :style="{ '--tint': s.tint }" @click="copy(s.command)">
              <span class="ws-ico"><Ico :name="s.icon" /></span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b><span>{{ s.text }}</span>
            </button>
          </div>
          <p class="ws-note" role="status">{{ copied || 'Every answer from an agent is written by a model playing invented people. Check decisions with real people.' }}</p>
        </div>

        <div v-else-if="view === 'projects'" class="ws-section ws-page">
          <header class="ws-page-head"><h1><Ico name="folder" :size="20" />Projects</h1><p>{{ runs.length }} saved runs in {{ root }}<template v-if="looseSims.length"> and {{ looseSims.length }} simulations on this backend</template>.</p></header>
          <div class="ws-toolbar">
            <label class="ws-inbox-search"><Ico name="search" /><input v-model="search" type="search" placeholder="Filter runs" aria-label="Filter runs" /></label>
            <div class="ws-seg" role="group" aria-label="Decision">
              <button v-for="d in decisions" :key="d.id" type="button" :aria-pressed="decisionFilter === d.id" @click="decisionFilter = d.id">{{ d.label }}<span class="ws-seg-n">{{ d.n }}</span></button>
            </div>
            <label class="ws-sort"><span class="sr-only">Sort</span>
              <select v-model="sortBy" class="ws-chip" aria-label="Sort runs">
                <option value="new">Newest first</option>
                <option value="people">Most people</option>
                <option value="name">Name</option>
              </select>
            </label>
          </div>
          <div class="ws-list"><ChatCard v-for="r in projectRuns" :key="r.name" :item="runItem(r)" pinnable /></div>
          <p v-if="!projectRuns.length" class="ws-empty">{{ runs.length ? 'No run matches.' : runsNote }}</p>
          <template v-if="looseSims.length">
            <h3><Ico name="activity" :size="16" />Simulations on this backend <small>without a saved run folder</small></h3>
            <div class="ws-list"><ChatCard v-for="s in looseSims" :key="s.simulation_id" :item="simItem(s)" pinnable /></div>
          </template>
        </div>

        <div v-else-if="view === 'skills'" class="ws-section ws-page">
          <header class="ws-page-head"><h1><Ico name="zap" :size="20" />Skills</h1><p>Free ones run on saved files; paid ones call your model provider. Click one without a page to copy its command.</p></header>
          <div class="ws-cards">
            <component :is="s.to ? 'RouterLink' : 'button'" v-for="s in skills" :key="s.id" class="ws-card" :to="s.to" :style="{ '--tint': s.tint }" @click="s.to ? null : copy(s.command)">
              <span class="ws-ico"><Ico :name="s.icon" /></span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b>
              <span>{{ s.text }}</span>
              <span v-if="s.command" class="ws-cmd"><Ico name="copy" :size="12" />{{ s.command }}</span>
            </component>
          </div>
          <p class="ws-note" role="status">{{ copied || 'Skills run from your agent (Claude Code, Codex, Gemini) or the CLI.' }}</p>
        </div>

        <div v-else-if="view === 'connectors'" class="ws-section ws-page">
          <header class="ws-page-head"><h1><Ico name="plug" :size="20" />Connectors</h1><p>Your model provider and the real data you can bring in. Everything stays on this computer.</p></header>
          <div class="ws-provider" :class="{ on: provider.configured }">
            <span class="ws-agent-ico"><Ico name="cpu" :size="20" /></span>
            <div>
              <h2>{{ provider.models?.[0]?.model || 'No model yet' }} <span class="ws-tagx" :class="provider.configured ? 'accent' : 'warm'"><Ico :name="provider.configured ? 'done' : 'circle'" :size="12" />{{ provider.configured ? 'Connected' : 'Not connected' }}</span></h2>
              <p>{{ provider.models?.[0]?.provider || 'Pick a provider and add its key in model settings. Keys stay in your .env.' }}</p>
            </div>
            <a class="ws-btn primary" :href="settingsLink"><Ico name="settings" :size="14" />Model settings</a>
          </div>
          <h3><Ico name="database" :size="16" />Data connectors <small>Click to copy the command</small></h3>
          <div class="ws-cards">
            <button v-for="c in connectors" :key="c.id" type="button" class="ws-card" :style="{ '--tint': c.tint }" @click="copy(c.command)">
              <span class="ws-ico"><Ico :name="c.icon" /></span><span class="ws-tag">{{ c.tag }}</span><b>{{ c.name }}</b><span>{{ c.text }}</span>
              <span class="ws-cmd"><Ico name="copy" :size="12" />{{ c.command }}</span>
            </button>
          </div>
          <p class="ws-note" role="status">{{ copied || 'Agents with a GA4, PostHog, ads or CRM MCP server can pull the data for you.' }}</p>
        </div>
      </section>
    </main>

    <CommandPalette :open="paletteOpen" :items="paletteItems" @close="paletteOpen = false" />
    <div v-if="keysOpen" class="ws-modal-back" @mousedown.self="keysOpen = false">
      <div ref="keysBox" class="ws-keys" role="dialog" aria-modal="true" aria-labelledby="ws-keys-title" tabindex="-1" @keydown.esc="keysOpen = false">
        <header><h2 id="ws-keys-title"><Ico name="keyboard" :size="18" />Keyboard shortcuts</h2><button type="button" class="ws-icon-btn" aria-label="Close" @click="keysOpen = false"><Ico name="x" /></button></header>
        <dl>
          <div v-for="k in shortcuts" :key="k.what"><dt><kbd v-for="x in k.keys" :key="x">{{ x }}</kbd></dt><dd>{{ k.what }}</dd></div>
        </dl>
      </div>
    </div>
    <div class="ws-toast" role="status" aria-live="polite"><span v-if="toast"><Ico name="check" :size="14" />{{ toast }}</span></div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import RunView from '../components/workspace/RunView.vue'
import Inbox from '../components/workspace/Inbox.vue'
import CommandPalette from '../components/workspace/CommandPalette.vue'
import Compare from '../components/workspace/Compare.vue'
import Ico from '../components/workspace/Ico.vue'
import { api, token } from '../workspace/api.js'
import { AGENTS, agent, agentById, pending, pins, savedChats, timeAgo, togglePin } from '../workspace/agents.js'
import '../assets/workspace.css'

const route = useRoute()
const router = useRouter()
const runs = ref([]), sims = ref([]), reports = ref([]), chats = ref([])
const root = ref('mirofish_runs'), error = ref(''), search = ref(''), idea = ref(''), copied = ref(''), toast = ref('')
const provider = ref({ configured: false, models: [] }), menuOpen = ref(false), homeBox = ref(null), fileInput = ref(null), keysBox = ref(null)
const hasToken = ref(true), loaded = ref(false), attachment = ref(null), mentionOpen = ref(false), mentionQ = ref(''), targetKey = ref('')
const paletteOpen = ref(false), keysOpen = ref(false), decisionFilter = ref('all'), sortBy = ref('new')
const rail = ref((() => {
  try {
    return localStorage.getItem('mm-rail') === '1'
  } catch {
    return false
  }
})())
function toggleRail() {
  rail.value = !rail.value
  try {
    localStorage.setItem('mm-rail', rail.value ? '1' : '0')
  } catch {
    /* holds for this page */
  }
}
const theme = ref((() => {
  try {
    return localStorage.getItem('mm-theme') || 'dark'
  } catch {
    return 'dark'
  }
})())
const modKey = /Mac|iPhone|iPad/.test(navigator.platform || '') ? '⌘' : 'Ctrl '

const short = (s, n = 26) => (String(s || '').length > n ? String(s).slice(0, n - 1) + '…' : String(s || ''))
const view = computed(() => (route.params.run ? 'run' : route.params.sim ? 'sim' : route.params.page || 'home'))
const nav = [
  { id: 'agents', label: 'Agents', icon: 'bot', to: '/workspace/agents' },
  { id: 'home', label: 'Home', icon: 'home', to: '/workspace' },
  { id: 'inbox', label: 'Inbox', icon: 'inbox', to: '/workspace/inbox' },
  { id: 'projects', label: 'Projects', icon: 'folder', to: '/workspace/projects' },
  { id: 'compare', label: 'Compare', icon: 'compare', to: '/workspace/compare' },
  { id: 'skills', label: 'Skills', icon: 'zap', to: '/workspace/skills' },
  { id: 'connectors', label: 'Connectors', icon: 'plug', to: '/workspace/connectors' }
]
const greeting = computed(() => {
  const hr = new Date().getHours()
  return hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening'
})
const initials = 'Y'
const runsNote = computed(() => (!loaded.value ? 'Loading runs…' : 'No saved runs yet. Run a market test, then it shows up here.'))
const modelName = computed(() => (provider.value.configured ? short(provider.value.models?.[0]?.model || 'Model', 22) : 'No model'))
const providerLine = computed(() => (provider.value.configured ? provider.value.models?.[0]?.model || 'Model connected' : 'No model connected'))
const settingsLink = computed(() => `/setup#t=${encodeURIComponent(token())}`)
const homePlaceholder = computed(() => ({
  run: 'Ask about a run: which audience, why people said no, which ad worked…',
  report: 'Ask the report agent about the run… (type @ to pick a run)',
  person: 'Ask a simulated buyer anything, e.g. would you pay $9 a month?',
  focus: 'One discussion question per line for a focus group…'
})[agent.value])

// runs and simulations as sidebar / mention targets
const runSims = computed(() => new Set(runs.value.map((r) => r.simulation_id).filter(Boolean)))
const looseSims = computed(() => sims.value.filter((s) => !runSims.value.has(s.simulation_id) && s.profiles_count))
const allTargets = computed(() => [
  ...runs.value.map((r) => ({ key: 'r:' + r.name, kind: 'run', name: r.name, title: r.title, people: r.people, decision: r.decision, to: `/workspace/runs/${r.name}` })),
  ...looseSims.value.map((s) => ({ key: 's:' + s.simulation_id, kind: 'sim', name: s.simulation_id, title: s.simulation_id, people: s.profiles_count, to: `/workspace/sims/${s.simulation_id}` }))
])
const mentionRuns = computed(() => {
  const q = mentionQ.value.trim().toLowerCase()
  return q ? allTargets.value.filter((r) => r.title.toLowerCase().includes(q)) : allTargets.value
})
const target = computed(() => allTargets.value.find((r) => r.key === targetKey.value) || allTargets.value[0] || null)
const pinnedRuns = computed(() => pins.value.map((k) => allTargets.value.find((t) => t.key === k)).filter(Boolean))
const recentRuns = computed(() => allTargets.value.filter((t) => !pins.value.includes(t.key)).slice(0, 14))
const totalPeople = computed(() => runs.value.reduce((s, r) => s + (Number(r.people) || 0), 0))
const readyReports = computed(() => reports.value.filter((r) => r.status === 'completed').length)

const reportFor = (sid) => reports.value.find((r) => r.simulation_id === sid && r.status === 'completed')
const when = (x) => {
  if (!x) return ''
  try {
    return new Date(x).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return ''
  }
}
function runItem(r) {
  const rep = r.simulation_id && reportFor(r.simulation_id)
  return {
    key: 'r:' + r.name, pin: 'r:' + r.name, to: `/workspace/runs/${r.name}`, title: r.title, decision: r.decision, icon: 'folder',
    line: [r.people ? `${Number(r.people).toLocaleString()} simulated people` : '', rep ? 'report ready' : '', when(r.updated_at || r.mtime * 1000)].filter(Boolean).join(' · ')
  }
}
function simItem(s) {
  const rep = reportFor(s.simulation_id)
  return {
    key: 's:' + s.simulation_id, pin: 's:' + s.simulation_id, to: `/workspace/sims/${s.simulation_id}`, title: rep?.outline?.title || s.simulation_id, icon: 'activity',
    line: [`${s.profiles_count} simulated people`, s.status, rep ? 'report ready' : '', when(s.updated_at || s.created_at)].filter(Boolean).join(' · ')
  }
}
const chatItems = computed(() => chats.value.map((c) => {
  const t = allTargets.value.find((x) => x.name === c.run)
  if (!t) return null
  return { ...c, key: 'c:' + c.run, type: 'chat', pin: t.key, to: t.to, title: t.title, decision: t.decision }
}).filter(Boolean))
const reportItems = computed(() => reports.value.filter((r) => r.status === 'completed').map((r) => {
  const t = allTargets.value.find((x) => (x.kind === 'run' ? runs.value.find((y) => y.name === x.name)?.simulation_id : x.name) === r.simulation_id)
  if (!t) return null
  return { key: 'rep:' + r.report_id, type: 'report', pin: t.key, to: t.to, title: r.outline?.title || t.title, decision: t.decision,
    at: r.completed_at || r.created_at, line: r.outline?.summary || `Report on ${t.title}` }
}).filter(Boolean))
const inboxItems = computed(() => [...chatItems.value, ...reportItems.value].sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0)))
const previous = computed(() => {
  const seen = new Set()
  const out = []
  for (const c of chatItems.value) {
    seen.add(c.pin)
    out.push({ key: c.key, pin: c.pin, to: c.to, title: c.title, decision: c.decision, icon: agentById(c.agent).icon, line: `${c.who}: ${c.last}`, badge: `${c.count} messages`, when: timeAgo(c.at) })
  }
  for (const r of runs.value) if (!seen.has('r:' + r.name)) out.push(runItem(r))
  for (const s of looseSims.value) if (!seen.has('s:' + s.simulation_id)) out.push(simItem(s))
  return out
})

const decisions = computed(() => {
  const count = (d) => runs.value.filter((r) => String(r.decision || '').toLowerCase() === d).length
  return [{ id: 'all', label: 'All', n: runs.value.length }, { id: 'go', label: 'Go', n: count('go') }, { id: 'iterate', label: 'Iterate', n: count('iterate') },
    { id: 'stop', label: 'No-go', n: runs.value.filter((r) => /stop|no.?go/i.test(r.decision || '')).length }]
})
const projectRuns = computed(() => {
  const q = search.value.trim().toLowerCase()
  let list = runs.value.filter((r) => !q || `${r.title} ${r.name}`.toLowerCase().includes(q))
  if (decisionFilter.value === 'stop') list = list.filter((r) => /stop|no.?go/i.test(r.decision || ''))
  else if (decisionFilter.value !== 'all') list = list.filter((r) => String(r.decision || '').toLowerCase() === decisionFilter.value)
  if (sortBy.value === 'people') list = [...list].sort((a, b) => (Number(b.people) || 0) - (Number(a.people) || 0))
  if (sortBy.value === 'name') list = [...list].sort((a, b) => String(a.title).localeCompare(String(b.title)))
  return list
})

const quick = [
  { icon: 'target', label: 'Which audience?', text: 'Which audience should we target?', agent: 'run' },
  { icon: 'no', label: 'Why did people say no?', text: 'Why did people say no?', agent: 'run' },
  { icon: 'megaphone', label: 'Best ad', text: 'Which ad worked best?', agent: 'run' },
  { icon: 'dollar', label: 'Ask a buyer about price', text: 'Would you pay $9 a month for this? Why or why not?', agent: 'person' },
  { icon: 'sparkles', label: 'Next steps from the report', text: 'What are the three changes most likely to lift sign-ups, and what evidence in the run supports each?', agent: 'report' },
  { icon: 'users', label: 'Focus group', text: 'What is your first reaction to this offer?\nWhat would stop you from signing up?', agent: 'focus' }
]
const skills = [
  { id: 'compare', icon: 'layers', name: 'Compare two ideas', tag: 'Guided', tint: 'rgba(242, 107, 42, 0.16)', to: '/', words: /ad|headline|landing|email|trial|offer|concept|pack|statement|job|hiring|appeal|donat|fundrais|two|version|compare|a\/b/i, text: 'Ads, landing pages, emails, offers, concepts, statements, job posts and appeals, side by side.' },
  { id: 'market', icon: 'globe', name: 'Full market test', tag: 'Paid', tint: 'rgba(79, 124, 214, 0.16)', command: 'mirofish.py quickstart', words: /launch|market|campaign|brand|full|everything/i, text: 'People, feeds, survey, pitch and report from one brief. Asks before spending.' },
  { id: 'questionnaire', icon: 'file', name: 'Your own questionnaire', tag: 'Paid', tint: 'rgba(162, 89, 196, 0.16)', command: 'mirofish.py questionnaire --simulation <sim> --questions @q.md', words: /survey|questionnaire|tracker|nps|question/i, text: 'Your questions as written, answered by the simulated people, with option order shuffled.' },
  { id: 'focus', icon: 'users', name: 'Focus group', tag: 'Paid', tint: 'rgba(42, 161, 161, 0.16)', command: 'mirofish.py focus-group --simulation <sim> --guide @guide.md', words: /focus|group|discussion|interview|talk/i, text: 'Private verdict, discussion, private verdict again, with a conformity check.' },
  { id: 'price', icon: 'dollar', name: 'Price check', tag: 'Paid', tint: 'rgba(217, 162, 59, 0.18)', command: 'mirofish.py choice-test --simulation <sim> --kind gabor_granger --spec @prices.json', words: /price|pricing|pay|cost|plan/i, text: 'Demand at each price and the revenue-maximising price, as a direction.' },
  { id: 'pitch', icon: 'phone', name: 'Sales pitch rehearsal', tag: 'Paid', tint: 'rgba(200, 88, 75, 0.14)', command: 'mirofish.py pitch --simulation <sim> --script @pitch.md --rebuttals @rebuttals.md', words: /pitch|sales|call|rebuttal|objection/i, text: 'Every person hears the pitch; hesitant ones hear your rebuttal.' },
  { id: 'research', icon: 'search', name: 'What real people say', tag: 'Free', tint: 'rgba(31, 107, 79, 0.14)', command: 'mirofish.py research --query "<topic>" --country us', words: /research|reddit|review|real people|voices/i, text: 'Public posts and reviews on your topic, saved as voices for the personas.' },
  { id: 'forecast', icon: 'lock', name: 'Lock a forecast', tag: 'Free', tint: 'rgba(90, 107, 140, 0.16)', command: 'mirofish.py forecast lock --run-dir mirofish_runs/<run> --due <date>', words: /forecast|predict|lock|score/i, text: 'Hash what a run predicts before the real result, then score it later.' },
  { id: 'calibrate', icon: 'gauge', name: 'Check against real answers', tag: 'Free', tint: 'rgba(122, 139, 47, 0.16)', command: 'mirofish.py calibrate --run-dir mirofish_runs/<run> --real answers.csv', words: /calibrat|real answer|accurate|trust|check/i, text: 'Compare simulated answers with real ones: intervals, spread and per-audience trust.' }
]
const suggested = [
  { id: 'q-objections', icon: 'no', name: 'Why did people say no?', tag: 'Free', tint: 'rgba(200, 88, 75, 0.14)', agent: 'run',
    prompt: 'Why did people say no?', text: 'Objections from a saved run, with a chart. No model call.' },
  { id: 'q-person', icon: 'user', name: 'Talk to a simulated buyer', tag: 'Model call', tint: 'rgba(79, 124, 214, 0.16)', agent: 'person',
    prompt: 'Would you pay for this? What would make you sign up today?', text: 'Pick a person in a run and ask anything. Their answers are simulated.' },
  ...skills.filter((s) => ['compare', 'price', 'calibrate'].includes(s.id))
]
const connectors = [
  { id: 'ga4', icon: 'trend', name: 'Google Analytics 4', tag: 'CSV or MCP', tint: 'rgba(242, 107, 42, 0.14)', command: 'mirofish.py analytics-audience --files ga4.csv', text: 'Size segments from your real audience: countries, channels, devices.' },
  { id: 'posthog', icon: 'chart', name: 'PostHog', tag: 'Export or MCP', tint: 'rgba(217, 162, 59, 0.16)', command: 'mirofish.py analytics-audience --files posthog.json', text: 'Persons and events exports become segment shares and population weights.' },
  { id: 'ads', icon: 'megaphone', name: 'Ad accounts', tag: 'CSV', tint: 'rgba(79, 124, 214, 0.14)', command: 'mirofish.py ads-import export.csv --out scenarios/x/past_ads.md', text: 'Past ads from Meta, Google or TikTok as benchmarks and seed.' },
  { id: 'crm', icon: 'users', name: 'Customers and reviews', tag: 'CSV / text', tint: 'rgba(31, 107, 79, 0.14)', command: 'mirofish.py intake --files reviews.csv calls/*.txt --out scenarios/x/personas.json', text: 'Your own customers become grounded personas. Contact details are removed locally.' },
  { id: 'real', icon: 'done', name: 'Real answers', tag: 'CSV', tint: 'rgba(122, 139, 47, 0.16)', command: 'mirofish.py calibrate --run-dir mirofish_runs/<run> --real answers.csv', text: 'Answers from real people to check the simulated ones.' },
  { id: 'agents', icon: 'bot', name: 'Claude Code, Codex, Gemini', tag: 'MCP', tint: 'rgba(162, 89, 196, 0.14)', command: '/plugin install market-mirror', text: 'Run every skill from your agent; it can pull data from its own connectors.' }
]
const shortcuts = [
  { keys: [modKey.trim(), 'K'], what: 'Search or jump to a run, page, agent or action' },
  { keys: ['/'], what: 'Same, from anywhere outside a text box' },
  { keys: ['Alt', '1–4'], what: 'Switch agent: Results, Report agent, Person, Focus group' },
  { keys: [modKey.trim(), 'B'], what: 'Collapse or expand the sidebar' },
  { keys: ['Enter'], what: 'Send (Shift Enter for a new line; Focus group: Ctrl Enter sends)' },
  { keys: ['@'], what: 'Pick the run in the home chat box' },
  { keys: ['↑', '↓'], what: 'Move through suggestions, the inbox and the palette' },
  { keys: ['←', '→'], what: 'Move between the visual tabs beside a chat' },
  { keys: ['?'], what: 'Show these shortcuts' },
  { keys: ['Esc'], what: 'Close a menu or dialog' }
]

const paletteItems = computed(() => [
  ...nav.map((n) => ({ id: 'n:' + n.id, group: 'Go to', label: n.label, icon: n.icon, run: () => router.push(n.to) })),
  ...AGENTS.map((a, i) => ({ id: 'a:' + a.id, group: 'Agents', label: `Ask ${a.label}`, hint: `${a.paid ? 'model calls' : 'free'} · Alt ${i + 1}`, icon: a.icon, run: () => (agent.value = a.id) })),
  ...allTargets.value.map((t) => ({ id: 't:' + t.key, group: 'Runs', label: t.title, hint: [t.people ? `${Number(t.people).toLocaleString()} people` : t.kind, t.name !== t.title ? t.name : ''].filter(Boolean).join(' · '), icon: pins.value.includes(t.key) ? 'pin' : t.kind === 'sim' ? 'activity' : 'folder', run: () => router.push(t.to) })),
  { id: 'x:new', group: 'Actions', label: 'New chat', icon: 'plus', run: () => router.push('/workspace') },
  { id: 'x:theme', group: 'Actions', label: theme.value === 'dark' ? 'Switch to light mode' : 'Switch to dark mode', icon: theme.value === 'dark' ? 'sun' : 'moon', run: toggleTheme },
  { id: 'x:keys', group: 'Actions', label: 'Keyboard shortcuts', icon: 'keyboard', run: () => (keysOpen.value = true) },
  { id: 'x:rail', group: 'Actions', label: rail.value ? 'Expand the sidebar' : 'Collapse the sidebar', icon: rail.value ? 'expand' : 'collapse', run: toggleRail },
  ...(runs.value.length > 1 ? [{ id: 'x:compare', group: 'Actions', label: 'Compare two runs', icon: 'compare', run: () => router.push('/workspace/compare') }] : []),
  { id: 'x:settings', group: 'Actions', label: 'Model settings', icon: 'settings', run: () => (location.href = settingsLink.value) }
])

const matches = ref([])
function useQuick(q) {
  agent.value = q.agent
  idea.value = q.prompt || q.text
  nextTick(() => homeBox.value?.focus())
}
function pickTarget(r) {
  targetKey.value = r.key
  mentionOpen.value = false
  mentionQ.value = ''
  if (idea.value.endsWith('@')) idea.value = idea.value.slice(0, -1)
  nextTick(() => homeBox.value?.focus())
}
function onHomeKey(e) {
  if (e.isComposing || e.keyCode === 229) return // Enter confirms an IME composition, it does not send
  if (e.key === '@') mentionOpen.value = true
  else if (e.key === 'Escape') mentionOpen.value = false
  else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || (!e.shiftKey && agent.value !== 'focus'))) {
    e.preventDefault()
    sendHome()
  }
}
async function onAttach(e) {
  const f = e.target.files?.[0]
  e.target.value = ''
  if (!f) return
  if (f.size > 60000) {
    error.value = 'Attach a text file under 60 KB.'
    return
  }
  attachment.value = { name: f.name, text: (await f.text()).slice(0, 60000) }
}
function sendHome() {
  const text = idea.value.trim()
  if (!text) return
  const t = target.value
  if (!t) {
    const hit = skills.filter((s) => s.words.test(text))
    matches.value = (hit.length ? hit : skills.slice(0, 3)).slice(0, 3)
    return
  }
  pending.value = { text, agent: agent.value, attachment: attachment.value }
  idea.value = ''
  attachment.value = null
  router.push(t.to)
}

async function copy(command) {
  if (!command) return
  try {
    await navigator.clipboard.writeText(command)
    copied.value = `Copied: ${command}`
    flash('Command copied')
  } catch {
    copied.value = command
  }
}
let toastTimer = null
function flash(text) {
  toast.value = text
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 2200)
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  try {
    localStorage.setItem('mm-theme', theme.value)
  } catch {
    /* the theme still changes for this page */
  }
}
watch(keysOpen, (v) => v && nextTick(() => keysBox.value?.focus()))
watch(() => route.fullPath, () => {
  menuOpen.value = false
  mentionOpen.value = false
})

function onKey(e) {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) || document.activeElement?.isContentEditable
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
  } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b' && !typing) {
    e.preventDefault()
    toggleRail()
  } else if (e.altKey && /^[1-4]$/.test(e.key)) {
    e.preventDefault()
    agent.value = AGENTS[Number(e.key) - 1].id
    flash(`${AGENTS[Number(e.key) - 1].label} answers next`)
  } else if (!typing && e.key === '/') {
    e.preventDefault()
    paletteOpen.value = true
  } else if (!typing && e.key === '?') {
    e.preventDefault()
    keysOpen.value = true
  } else if (e.key === 'Escape') {
    menuOpen.value = false
    mentionOpen.value = false
  }
}
const refreshChats = () => (chats.value = savedChats())

onMounted(async () => {
  document.addEventListener('keydown', onKey)
  window.addEventListener('mm-chat-saved', refreshChats)
  refreshChats()
  hasToken.value = !!token()
  if (!hasToken.value) return
  try {
    const [list, meta, simList, repList] = await Promise.all([
      api('/api/runs'),
      api('/api/workflows/meta').catch(() => null),
      api('/api/simulation/list').catch(() => []),
      api('/api/report/list?limit=100').catch(() => [])
    ])
    runs.value = list.runs
    root.value = list.root.split('/').slice(-1)[0]
    if (meta?.provider) provider.value = meta.provider
    sims.value = Array.isArray(simList) ? simList : []
    reports.value = Array.isArray(repList) ? repList : []
  } catch (e) {
    error.value = e.message
  } finally {
    loaded.value = true
  }
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKey)
  window.removeEventListener('mm-chat-saved', refreshChats)
})

const dot = (d) => (/go$/i.test(d || '') && !/no/i.test(d) ? 'go' : /iterate/i.test(d || '') ? 'iterate' : d ? 'stop' : 'none')
const RunLink = defineComponent({
  props: { item: { type: Object, required: true } },
  setup(p) {
    return () => h('div', { class: ['ws-run-link', { active: route.path === p.item.to }] }, [
      h(RouterLink, { to: p.item.to, title: p.item.title, 'aria-current': route.path === p.item.to ? 'page' : undefined }, () => [
        h('span', { class: `ws-dec ${dot(p.item.decision)}`, 'aria-hidden': 'true' }),
        h('span', { class: 'ws-run-name' }, p.item.title),
        p.item.decision ? h('span', { class: 'sr-only' }, `, ${p.item.decision}`) : null
      ]),
      h('button', {
        type: 'button', class: 'ws-pin-btn', 'aria-pressed': String(pins.value.includes(p.item.key)),
        'aria-label': `${pins.value.includes(p.item.key) ? 'Unpin' : 'Pin'} ${p.item.title}`, onClick: () => togglePin(p.item.key)
      }, [h(Ico, { name: pins.value.includes(p.item.key) ? 'unpin' : 'pin', size: 13 })])
    ])
  }
})
const ChatCard = defineComponent({
  props: { item: { type: Object, required: true }, pinnable: Boolean },
  setup(p, { attrs }) {
    return () => h('div', { class: 'ws-card-wrap', role: attrs.role }, [
      h(RouterLink, { to: p.item.to, class: 'ws-card', style: { '--tint': 'rgba(95, 199, 154, 0.1)' } }, () => [
        h('span', { class: 'ws-ico' }, [h(Ico, { name: p.item.icon })]),
        p.item.decision
          ? h('span', { class: `ws-tag pill ${String(p.item.decision).toLowerCase().replace(' ', '-')}` }, String(p.item.decision).toUpperCase())
          : p.item.badge ? h('span', { class: 'ws-tag' }, p.item.badge) : null,
        h('b', p.item.title),
        h('span', p.item.line),
        p.item.when ? h('small', { class: 'ws-card-when' }, [h(Ico, { name: 'clock', size: 12 }), p.item.when]) : null
      ]),
      p.pinnable && p.item.pin
        ? h('button', {
          type: 'button', class: 'ws-card-pin', 'aria-pressed': String(pins.value.includes(p.item.pin)),
          'aria-label': `${pins.value.includes(p.item.pin) ? 'Unpin' : 'Pin'} ${p.item.title}`, onClick: () => togglePin(p.item.pin)
        }, [h(Ico, { name: pins.value.includes(p.item.pin) ? 'unpin' : 'pin', size: 14 })])
        : null
    ])
  }
})
</script>

<style>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
