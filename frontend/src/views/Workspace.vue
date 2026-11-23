<template>
  <div class="ws" :data-theme="theme">
    <a class="ws-skip" href="#ws-canvas">Skip to content</a>
    <nav class="ws-side" :class="{ open: menuOpen }" aria-label="Workspace">
      <details class="ws-switch">
        <summary>
          <i aria-hidden="true">m</i>
          <span><b>MarketMirror</b><small>Local workspace</small></span>
          <span class="ws-caret" aria-hidden="true">▾</span>
        </summary>
        <div class="ws-switch-menu">
          <RouterLink to="/workspace">Workspace <small>this page</small></RouterLink>
          <RouterLink to="/">Compare two ideas <small>guided app</small></RouterLink>
          <a :href="settingsLink">Model settings <small>provider and keys</small></a>
        </div>
      </details>
      <label class="ws-search">
        <span aria-hidden="true">⌕</span>
        <input ref="searchBox" v-model="search" type="search" placeholder="Search runs and chats" aria-label="Search runs and chats" />
        <kbd aria-hidden="true">/</kbd>
      </label>
      <div class="ws-nav">
        <RouterLink to="/workspace/agents" :class="{ active: view === 'agents' }" @click="menuOpen = false"><span class="ico" aria-hidden="true">✦</span>Agents</RouterLink>
        <RouterLink to="/workspace" :class="{ active: view === 'home' }" @click="menuOpen = false"><span class="ico" aria-hidden="true">⌂</span>Home</RouterLink>
        <RouterLink to="/workspace/inbox" :class="{ active: view === 'inbox' }" @click="menuOpen = false">
          <span class="ico" aria-hidden="true">✉</span>Inbox<span v-if="inboxCount" class="ws-count" :aria-label="`${inboxCount} items`">{{ inboxCount }}</span>
        </RouterLink>
        <RouterLink to="/workspace/projects" :class="{ active: view === 'projects' }" @click="menuOpen = false"><span class="ico" aria-hidden="true">▦</span>Projects</RouterLink>
        <RouterLink to="/workspace/skills" :class="{ active: view === 'skills' }" @click="menuOpen = false"><span class="ico" aria-hidden="true">⚡</span>Skills</RouterLink>
        <RouterLink to="/workspace/connectors" :class="{ active: view === 'connectors' }" @click="menuOpen = false"><span class="ico" aria-hidden="true">⛓</span>Connectors</RouterLink>
      </div>
      <p class="ws-group" id="ws-runs-label">Runs</p>
      <div class="ws-history" aria-labelledby="ws-runs-label">
        <RouterLink
          v-for="r in filteredRuns.slice(0, 14)"
          :key="r.name"
          :to="`/workspace/runs/${r.name}`"
          :class="{ active: route.params.run === r.name }"
          :title="r.title"
          @click="menuOpen = false"
        >
          {{ r.title }}
        </RouterLink>
        <p v-if="!filteredRuns.length" class="ws-note" style="padding-left: 14px">{{ runsNote }}</p>
      </div>
      <div class="ws-foot">
        <div class="ws-nav">
          <button type="button" @click="toggleTheme"><span class="ico" aria-hidden="true">◐</span>{{ theme === 'dark' ? 'Light mode' : 'Dark mode' }}</button>
        </div>
        <div class="ws-me">
          <span class="ws-avatar" aria-hidden="true">Y</span>
          <div><b>You</b><span>{{ providerLine }}</span></div>
        </div>
      </div>
    </nav>
    <div v-if="menuOpen" class="ws-scrim" aria-hidden="true" @click="menuOpen = false"></div>

    <main class="ws-main">
      <header class="ws-top">
        <button type="button" class="ws-btn ws-menu-btn" :aria-expanded="menuOpen" aria-label="Open menu" @click="menuOpen = !menuOpen">☰</button>
        <div class="ws-agents" role="group" aria-label="Who answers your messages">
          <button
            v-for="a in AGENTS"
            :key="a.id"
            type="button"
            class="ws-agent-tab"
            :aria-pressed="agent === a.id"
            :title="a.title"
            @click="agent = a.id"
          >
            <span aria-hidden="true">{{ a.icon }}</span>{{ a.label }}<small v-if="a.paid" class="ws-paid" aria-label="model calls">$</small>
          </button>
          <RouterLink class="ws-agent-tab add" to="/workspace/agents" title="Every agent and what it costs">＋ Add agent</RouterLink>
        </div>
        <div class="ws-top-right">
          <a class="ws-btn" :href="settingsLink" title="Model provider and keys"><span aria-hidden="true">⚙</span><span class="ws-hide-sm"> Settings</span></a>
          <RouterLink class="ws-btn primary" to="/workspace">＋<span class="ws-hide-sm"> New chat</span></RouterLink>
        </div>
      </header>
      <p v-if="!hasToken" class="ws-error" role="alert">
        Open this workspace with <code>./mm app</code> so it can reach your local runs. The page needs the local session
        it starts.
      </p>
      <p v-else-if="error" class="ws-error" role="alert">{{ error }}</p>

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
                <span>📎 {{ attachment.name }} · {{ Math.round(attachment.text.length / 100) / 10 }}k characters</span>
                <button type="button" aria-label="Remove attachment" @click="attachment = null">×</button>
              </div>
              <textarea
                id="ws-home"
                ref="homeBox"
                v-model="idea"
                rows="3"
                :placeholder="homePlaceholder"
                @keydown="onHomeKey"
              ></textarea>
              <div class="ws-composer-row">
                <button type="button" class="ws-chip icon" aria-label="Attach a text file" title="Attach a text, Markdown or CSV file (stays in this browser until you send)" @click="fileInput.click()">📎</button>
                <input ref="fileInput" type="file" accept=".txt,.md,.csv,.json" class="sr-only" tabindex="-1" @change="onAttach" />
                <div class="ws-mention">
                  <button type="button" class="ws-chip" :aria-expanded="mentionOpen" aria-haspopup="listbox" title="Pick the run to talk about" @click="mentionOpen = !mentionOpen">
                    @ {{ target ? short(target.title, 28) : 'Pick a run' }}
                  </button>
                  <div v-if="mentionOpen" class="ws-suggest ws-mention-list" role="listbox" aria-label="Runs" @keydown.esc="mentionOpen = false">
                    <button v-for="r in mentionRuns" :key="r.key" type="button" role="option" :aria-selected="target?.key === r.key" @click="pickTarget(r)">
                      {{ r.title }} <small>{{ r.kind === 'sim' ? 'simulation' : r.people ? r.people + ' people' : 'run' }}</small>
                    </button>
                    <p v-if="!mentionRuns.length">{{ runsNote }}</p>
                  </div>
                </div>
                <RouterLink class="ws-chip" to="/workspace/skills">⚡ Skills</RouterLink>
                <a class="ws-chip" :href="settingsLink" :title="provider.configured ? 'Model used for paid agents' : 'Connect a model provider'">◎ {{ modelName }}</a>
                <button type="button" class="ws-send" :disabled="!idea.trim()" :aria-label="`Send to ${agentById(agent).label}`" @click="sendHome">↑</button>
              </div>
            </div>
            <p class="ws-note ws-cost" aria-live="polite">
              <b>{{ agentById(agent).label }}</b> ·
              {{ agentById(agent).paid ? 'sends model calls to your provider when you press send. Answers are simulated.' : 'answers from saved results, no model call.' }}
            </p>
            <div class="ws-quick" aria-label="Quick actions">
              <button v-for="q in quick" :key="q.text" type="button" class="ws-chip" @click="useQuick(q)">
                <span aria-hidden="true">{{ q.icon }}</span> {{ q.label }}
              </button>
            </div>
            <div v-if="matches.length" class="ws-cards" style="margin-top: 14px" aria-live="polite">
              <component :is="m.to ? 'RouterLink' : 'button'" v-for="m in matches" :key="m.id" class="ws-card" :to="m.to" :style="{ '--tint': m.tint }" @click="m.to ? null : copy(m.command)">
                <span class="ws-ico">{{ m.icon }}</span><span class="ws-tag">{{ m.tag }}</span>
                <b>{{ m.name }}</b><span>{{ m.to ? m.text : 'Copy: ' + m.command }}</span>
              </component>
            </div>
          </div>
          <div class="ws-section">
            <h3>Previous chats <RouterLink to="/workspace/inbox" class="ws-more">View all</RouterLink></h3>
            <div class="ws-row" role="list">
              <ChatCard v-for="c in previous.slice(0, 8)" :key="c.key" :item="c" role="listitem" />
            </div>
            <p v-if="!previous.length" class="ws-empty">{{ runsNote }}</p>
            <h3>Suggested <RouterLink to="/workspace/skills" class="ws-more">All skills</RouterLink></h3>
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
                <span class="ws-ico">{{ s.icon }}</span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b><span>{{ s.text }}</span>
              </component>
            </div>
            <p v-if="copied" class="ws-note">{{ copied }}</p>
          </div>
        </template>

        <div v-else-if="view === 'agents'" class="ws-section" style="padding-top: 24px">
          <h3>Agents <small>Pick who answers; the tabs at the top do the same</small></h3>
          <div class="ws-cards">
            <button v-for="a in AGENTS" :key="a.id" type="button" class="ws-card" :aria-pressed="agent === a.id" @click="agent = a.id">
              <span class="ws-ico">{{ a.icon }}</span><span class="ws-tag">{{ a.paid ? 'Model calls' : 'Free' }}</span>
              <b>{{ a.label }}</b><span>{{ a.text }}</span>
            </button>
          </div>
          <h3>More agents <small>Run from your coding agent or the CLI</small></h3>
          <div class="ws-cards">
            <button v-for="s in skills.filter((x) => x.command)" :key="s.id" type="button" class="ws-card" :style="{ '--tint': s.tint }" @click="copy(s.command)">
              <span class="ws-ico">{{ s.icon }}</span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b><span>{{ s.text }}</span>
            </button>
          </div>
          <p class="ws-note">{{ copied || 'Every answer from an agent is written by a model playing invented people. Check decisions with real people.' }}</p>
        </div>

        <div v-else-if="view === 'inbox'" class="ws-section" style="padding-top: 24px">
          <h3>Inbox <small>Chats saved in this browser and reports on this backend</small></h3>
          <div class="ws-list"><ChatCard v-for="c in filteredPrevious" :key="c.key" :item="c" /></div>
          <p v-if="!filteredPrevious.length" class="ws-empty">No chats yet. Open a run and ask a question.</p>
        </div>

        <div v-else-if="view === 'projects'" class="ws-section" style="padding-top: 24px">
          <h3>Projects <small>{{ filteredRuns.length }} saved runs in {{ root }}</small></h3>
          <div class="ws-list"><ChatCard v-for="r in filteredRuns" :key="r.name" :item="runItem(r)" /></div>
          <p v-if="!filteredRuns.length" class="ws-empty">{{ runsNote }}</p>
          <template v-if="looseSims.length">
            <h3>Simulations on this backend <small>without a saved run folder</small></h3>
            <div class="ws-list"><ChatCard v-for="s in looseSims" :key="s.simulation_id" :item="simItem(s)" /></div>
          </template>
        </div>

        <div v-else-if="view === 'skills'" class="ws-section" style="padding-top: 24px">
          <h3>Skills <small>Free ones run on saved files; paid ones call your model provider</small></h3>
          <div class="ws-cards">
            <component :is="s.to ? 'RouterLink' : 'button'" v-for="s in skills" :key="s.id" class="ws-card" :to="s.to" :style="{ '--tint': s.tint }" @click="s.to ? null : copy(s.command)">
              <span class="ws-ico">{{ s.icon }}</span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b>
              <span>{{ s.text }}</span>
              <span v-if="s.command" class="ws-cmd">{{ s.command }}</span>
            </component>
          </div>
          <p class="ws-note">{{ copied || 'Skills without a page run from your agent (Claude Code, Codex, Gemini) or the CLI; click to copy the command.' }}</p>
        </div>

        <div v-else-if="view === 'connectors'" class="ws-section" style="padding-top: 24px">
          <h3>Model providers <small>{{ provider.configured ? 'Connected' : 'Not connected yet' }}</small></h3>
          <div class="ws-cards">
            <div class="ws-card" style="--tint: rgba(31, 107, 79, 0.14); cursor: default">
              <span class="ws-ico">◎</span><span class="ws-tag">{{ provider.configured ? 'On' : 'Off' }}</span>
              <b>{{ provider.models?.[0]?.model || 'No model yet' }}</b>
              <span>{{ provider.models?.[0]?.provider || 'Pick a provider and add its key in model settings. Keys stay in your .env.' }}</span>
              <a class="ws-btn" style="margin-top: 12px" :href="settingsLink">Model settings</a>
            </div>
          </div>
          <h3>Data connectors <small>Bring real data in; it stays on this computer</small></h3>
          <div class="ws-cards">
            <button v-for="c in connectors" :key="c.id" type="button" class="ws-card" :style="{ '--tint': c.tint }" @click="copy(c.command)">
              <span class="ws-ico">{{ c.icon }}</span><span class="ws-tag">{{ c.tag }}</span><b>{{ c.name }}</b><span>{{ c.text }}</span>
              <span class="ws-cmd">{{ c.command }}</span>
            </button>
          </div>
          <p class="ws-note">{{ copied || 'Click a connector to copy its command. Agents with a GA4, PostHog, ads or CRM MCP server can pull the data for you.' }}</p>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import RunView from '../components/workspace/RunView.vue'
import { api, token } from '../workspace/api.js'
import { AGENTS, agent, agentById, pending, savedChats } from '../workspace/agents.js'
import '../assets/workspace.css'

const route = useRoute()
const router = useRouter()
const runs = ref([]), sims = ref([]), reports = ref([]), chats = ref([])
const root = ref('mirofish_runs'), error = ref(''), search = ref(''), idea = ref(''), copied = ref('')
const provider = ref({ configured: false, models: [] }), menuOpen = ref(false), searchBox = ref(null), homeBox = ref(null), fileInput = ref(null)
const hasToken = ref(true), loaded = ref(false), attachment = ref(null), mentionOpen = ref(false), targetKey = ref('')
const theme = ref((() => {
  try {
    return localStorage.getItem('mm-theme') || 'dark'
  } catch {
    return 'dark'
  }
})())

const short = (s, n = 26) => (String(s || '').length > n ? String(s).slice(0, n - 1) + '…' : String(s || ''))
const view = computed(() => (route.params.run ? 'run' : route.params.sim ? 'sim' : route.params.page || 'home'))
const greeting = computed(() => {
  const hr = new Date().getHours()
  return hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening'
})
const filteredRuns = computed(() => {
  const q = search.value.trim().toLowerCase()
  return q ? runs.value.filter((r) => `${r.title} ${r.name}`.toLowerCase().includes(q)) : runs.value
})
const runsNote = computed(() => (!loaded.value ? 'Loading runs…' : 'No saved runs yet. Run a market test, then it shows up here.'))
const modelName = computed(() => (provider.value.configured ? short(provider.value.models?.[0]?.model || 'Model', 22) : 'No model'))
const providerLine = computed(() => (provider.value.configured ? provider.value.models?.[0]?.model || 'Model connected' : 'No model connected'))
const settingsLink = computed(() => `/setup#t=${encodeURIComponent(token())}`)
const homePlaceholder = computed(() => ({
  run: 'Ask about a run: which audience, why people said no, which ad worked…',
  report: 'Ask the report agent about the run…  (type @ to pick a run)',
  person: 'Ask a simulated buyer anything, e.g. would you pay $9 a month?',
  focus: 'One discussion question per line for a focus group…'
})[agent.value])

// Simulations on this backend that have no saved run folder still open, read from the engine API.
const runSims = computed(() => new Set(runs.value.map((r) => r.simulation_id).filter(Boolean)))
const looseSims = computed(() => sims.value.filter((s) => !runSims.value.has(s.simulation_id) && s.profiles_count))
const mentionRuns = computed(() => [
  ...runs.value.map((r) => ({ key: 'r:' + r.name, kind: 'run', name: r.name, title: r.title, people: r.people })),
  ...looseSims.value.map((s) => ({ key: 's:' + s.simulation_id, kind: 'sim', name: s.simulation_id, title: s.simulation_id, people: s.profiles_count }))
])
const target = computed(() => mentionRuns.value.find((r) => r.key === targetKey.value) || mentionRuns.value[0] || null)

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
    key: 'r:' + r.name, to: `/workspace/runs/${r.name}`, title: r.title, decision: r.decision, icon: '▦',
    line: [r.people ? `${r.people} simulated people` : '', rep ? 'report ready' : '', when(r.updated_at || r.mtime * 1000)].filter(Boolean).join(' · ')
  }
}
function simItem(s) {
  const rep = reportFor(s.simulation_id)
  return {
    key: 's:' + s.simulation_id, to: `/workspace/sims/${s.simulation_id}`, title: rep?.outline?.title || s.simulation_id, icon: '◉',
    line: [`${s.profiles_count} simulated people`, s.status, rep ? 'report ready' : '', when(s.updated_at || s.created_at)].filter(Boolean).join(' · ')
  }
}
const previous = computed(() => {
  const seen = new Set()
  const out = []
  for (const c of chats.value) {
    const r = runs.value.find((x) => x.name === c.run)
    const s = !r && sims.value.find((x) => x.simulation_id === c.run)
    if (!r && !s) continue
    seen.add(c.run)
    out.push({ key: 'c:' + c.run, to: r ? `/workspace/runs/${r.name}` : `/workspace/sims/${s.simulation_id}`, title: r ? r.title : s.simulation_id,
      decision: r?.decision, icon: '✉', line: `${c.who}: ${c.last}`, badge: `${c.count} messages` })
  }
  for (const r of runs.value) if (!seen.has(r.name)) out.push(runItem(r))
  for (const s of looseSims.value) if (!seen.has(s.simulation_id)) out.push(simItem(s))
  return out
})
const filteredPrevious = computed(() => {
  const q = search.value.trim().toLowerCase()
  const list = previous.value.filter((p) => p.key.startsWith('c:') || p.line.includes('report ready'))
  return q ? list.filter((p) => `${p.title} ${p.line}`.toLowerCase().includes(q)) : list
})
const inboxCount = computed(() => previous.value.filter((p) => p.key.startsWith('c:') || p.line.includes('report ready')).length)

const quick = [
  { icon: '◎', label: 'Which audience?', text: 'Which audience should we target?', agent: 'run' },
  { icon: '✕', label: 'Why did people say no?', text: 'Why did people say no?', agent: 'run' },
  { icon: '▤', label: 'Best ad', text: 'Which ad worked best?', agent: 'run' },
  { icon: '☺', label: 'Ask a buyer about price', text: 'Would you pay $9 a month for this? Why or why not?', agent: 'person' },
  { icon: '✦', label: 'Next steps from the report', text: 'What are the three changes most likely to lift sign-ups, and what evidence in the run supports each?', agent: 'report' },
  { icon: '◉', label: 'Focus group', text: 'What is your first reaction to this offer?\nWhat would stop you from signing up?', agent: 'focus' }
]

const skills = [
  { id: 'compare', icon: '⇄', name: 'Compare two ideas', tag: 'Guided', tint: 'rgba(242, 107, 42, 0.16)', to: '/', words: /ad|headline|landing|email|trial|offer|concept|pack|statement|job|hiring|appeal|donat|fundrais|two|version|compare|a\/b/i, text: 'Ads, landing pages, emails, offers, concepts, statements, job posts and appeals, side by side.' },
  { id: 'market', icon: '◉', name: 'Full market test', tag: 'Paid', tint: 'rgba(79, 124, 214, 0.16)', command: 'mirofish.py quickstart', words: /launch|market|campaign|brand|full|everything/i, text: 'People, feeds, survey, pitch and report from one brief. Asks before spending.' },
  { id: 'questionnaire', icon: '☰', name: 'Your own questionnaire', tag: 'Paid', tint: 'rgba(162, 89, 196, 0.16)', command: 'mirofish.py questionnaire --simulation <sim> --questions @q.md', words: /survey|questionnaire|tracker|nps|question/i, text: 'Your questions as written, answered by the simulated people, with option order shuffled.' },
  { id: 'focus', icon: '◎', name: 'Focus group', tag: 'Paid', tint: 'rgba(42, 161, 161, 0.16)', command: 'mirofish.py focus-group --simulation <sim> --guide @guide.md', words: /focus|group|discussion|interview|talk/i, text: 'Private verdict, discussion, private verdict again, with a conformity check.' },
  { id: 'price', icon: '$', name: 'Price check', tag: 'Paid', tint: 'rgba(217, 162, 59, 0.18)', command: 'mirofish.py choice-test --simulation <sim> --kind gabor_granger --spec @prices.json', words: /price|pricing|pay|cost|plan/i, text: 'Demand at each price and the revenue-maximising price, as a direction.' },
  { id: 'pitch', icon: '☏', name: 'Sales pitch rehearsal', tag: 'Paid', tint: 'rgba(200, 88, 75, 0.14)', command: 'mirofish.py pitch --simulation <sim> --script @pitch.md --rebuttals @rebuttals.md', words: /pitch|sales|call|rebuttal|objection/i, text: 'Every person hears the pitch; hesitant ones hear your rebuttal.' },
  { id: 'research', icon: '⌕', name: 'What real people say', tag: 'Free', tint: 'rgba(31, 107, 79, 0.14)', command: 'mirofish.py research --query "<topic>" --country us', words: /research|reddit|review|real people|voices/i, text: 'Public posts and reviews on your topic, saved as voices for the personas.' },
  { id: 'forecast', icon: '⌛', name: 'Lock a forecast', tag: 'Free', tint: 'rgba(90, 107, 140, 0.16)', command: 'mirofish.py forecast lock --run-dir mirofish_runs/<run> --due <date>', words: /forecast|predict|lock|score/i, text: 'Hash what a run predicts before the real result, then score it later.' },
  { id: 'calibrate', icon: '≈', name: 'Check against real answers', tag: 'Free', tint: 'rgba(122, 139, 47, 0.16)', command: 'mirofish.py calibrate --run-dir mirofish_runs/<run> --real answers.csv', words: /calibrat|real answer|accurate|trust|check/i, text: 'Compare simulated answers with real ones: intervals, spread and per-audience trust.' }
]
const suggested = [
  { id: 'q-objections', icon: '✕', name: 'Why did people say no?', tag: 'Free', tint: 'rgba(200, 88, 75, 0.14)', agent: 'run',
    prompt: 'Why did people say no?', text: 'Objections from a saved run, with a chart. No model call.' },
  { id: 'q-person', icon: '☺', name: 'Talk to a simulated buyer', tag: 'Model call', tint: 'rgba(79, 124, 214, 0.16)', agent: 'person',
    prompt: 'Would you pay for this? What would make you sign up today?', text: 'Pick a person in a run and ask anything. Their answers are simulated.' },
  ...skills.filter((s) => ['compare', 'price', 'calibrate'].includes(s.id))
]
const connectors = [
  { id: 'ga4', icon: '📈', name: 'Google Analytics 4', tag: 'CSV or MCP', tint: 'rgba(242, 107, 42, 0.14)', command: 'mirofish.py analytics-audience --files ga4.csv', text: 'Size segments from your real audience: countries, channels, devices.' },
  { id: 'posthog', icon: '🦔', name: 'PostHog', tag: 'Export or MCP', tint: 'rgba(217, 162, 59, 0.16)', command: 'mirofish.py analytics-audience --files posthog.json', text: 'Persons and events exports become segment shares and population weights.' },
  { id: 'ads', icon: '📣', name: 'Ad accounts', tag: 'CSV', tint: 'rgba(79, 124, 214, 0.14)', command: 'mirofish.py ads-import export.csv --out scenarios/x/past_ads.md', text: 'Past ads from Meta, Google or TikTok as benchmarks and seed.' },
  { id: 'crm', icon: '👥', name: 'Customers and reviews', tag: 'CSV / text', tint: 'rgba(31, 107, 79, 0.14)', command: 'mirofish.py intake --files reviews.csv calls/*.txt --out scenarios/x/personas.json', text: 'Your own customers become grounded personas. Contact details are removed locally.' },
  { id: 'real', icon: '✓', name: 'Real answers', tag: 'CSV', tint: 'rgba(122, 139, 47, 0.16)', command: 'mirofish.py calibrate --run-dir mirofish_runs/<run> --real answers.csv', text: 'Answers from real people to check the simulated ones.' },
  { id: 'agents', icon: '✦', name: 'Claude Code, Codex, Gemini', tag: 'MCP', tint: 'rgba(162, 89, 196, 0.14)', command: '/plugin install market-mirror', text: 'Run every skill from your agent; it can pull data from its own connectors.' }
]

const matches = ref([])
function useQuick(q) {
  agent.value = q.agent
  idea.value = q.prompt || q.text
  nextTick(() => homeBox.value?.focus())
}
function pickTarget(r) {
  targetKey.value = r.key
  mentionOpen.value = false
  if (idea.value.endsWith('@')) idea.value = idea.value.slice(0, -1)
  nextTick(() => homeBox.value?.focus())
}
function onHomeKey(e) {
  if (e.key === '@') mentionOpen.value = true
  else if (e.key === 'Escape') mentionOpen.value = false
  else if (e.key === 'Enter' && !e.shiftKey && agent.value !== 'focus') {
    e.preventDefault()
    sendHome()
  } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
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
    // no runs to talk to: point to the skill that fits instead
    const hit = skills.filter((s) => s.words.test(text))
    matches.value = (hit.length ? hit : skills.slice(0, 3)).slice(0, 3)
    return
  }
  pending.value = { text, agent: agent.value, attachment: attachment.value }
  idea.value = ''
  attachment.value = null
  router.push(t.kind === 'sim' ? `/workspace/sims/${t.name}` : `/workspace/runs/${t.name}`)
}

async function copy(command) {
  if (!command) return
  try {
    await navigator.clipboard.writeText(command)
    copied.value = `Copied: ${command}`
  } catch {
    copied.value = command
  }
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  try {
    localStorage.setItem('mm-theme', theme.value)
  } catch {
    /* the theme still changes for this page */
  }
}

function onSlash(e) {
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
    e.preventDefault()
    searchBox.value?.focus()
  } else if (e.key === 'Escape') {
    menuOpen.value = false
  }
}
const refreshChats = () => (chats.value = savedChats())

onMounted(async () => {
  document.addEventListener('keydown', onSlash)
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
  document.removeEventListener('keydown', onSlash)
  window.removeEventListener('mm-chat-saved', refreshChats)
})

const ChatCard = defineComponent({
  props: { item: { type: Object, required: true } },
  setup(p, { attrs }) {
    return () => h(RouterLink, { to: p.item.to, class: 'ws-card', role: attrs.role, style: { '--tint': 'rgba(95, 199, 154, 0.1)' } }, () => [
      h('span', { class: 'ws-ico', 'aria-hidden': 'true' }, p.item.icon),
      p.item.decision
        ? h('span', { class: `ws-tag pill ${String(p.item.decision).toLowerCase().replace(' ', '-')}` }, String(p.item.decision).toUpperCase())
        : p.item.badge ? h('span', { class: 'ws-tag' }, p.item.badge) : null,
      h('b', p.item.title),
      h('span', p.item.line)
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
