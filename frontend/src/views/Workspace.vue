<template>
  <div class="ws" :data-theme="theme">
    <nav class="ws-side" :class="{ open: menuOpen }" aria-label="Workspace">
      <div class="ws-brand"><i aria-hidden="true">m</i>MarketMirror</div>
      <label class="ws-search">
        <span aria-hidden="true">⌕</span>
        <input ref="searchBox" v-model="search" type="search" placeholder="Search runs" aria-label="Search runs" />
        <kbd>/</kbd>
      </label>
      <div class="ws-nav">
        <RouterLink to="/workspace" :class="{ active: view === 'home' }" @click="menuOpen = false"><span class="ico">✦</span>Chat</RouterLink>
        <RouterLink to="/workspace/projects" :class="{ active: view === 'projects' }" @click="menuOpen = false"><span class="ico">▦</span>Projects</RouterLink>
        <RouterLink to="/workspace/skills" :class="{ active: view === 'skills' }" @click="menuOpen = false"><span class="ico">⚡</span>Skills</RouterLink>
        <RouterLink to="/workspace/connectors" :class="{ active: view === 'connectors' }" @click="menuOpen = false"><span class="ico">⛓</span>Connectors</RouterLink>
        <RouterLink to="/"><span class="ico">⇄</span>Compare two ideas</RouterLink>
      </div>
      <p class="ws-group">Recent runs</p>
      <div class="ws-history">
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
          <button @click="toggleTheme"><span class="ico">◐</span>{{ theme === 'dark' ? 'Light mode' : 'Dark mode' }}</button>
        </div>
        <div class="ws-me">
          <span class="ws-avatar" aria-hidden="true"></span>
          <div><b>Local workspace</b><span>{{ providerLine }}</span></div>
        </div>
      </div>
    </nav>

    <main class="ws-main">
      <header class="ws-top">
        <div class="ws-crumbs">
          <button class="ws-btn ws-menu-btn" aria-label="Open menu" @click="menuOpen = !menuOpen">☰</button>
          <span>MarketMirror</span><span aria-hidden="true">/</span><b>{{ crumb }}</b>
        </div>
        <RouterLink class="ws-btn primary" to="/workspace">＋ New chat</RouterLink>
      </header>
      <p v-if="!hasToken" class="ws-error" role="alert">
        Open this workspace with <code>./mm app</code> so it can reach your local runs. The page needs the local session
        it starts.
      </p>
      <p v-else-if="error" class="ws-error" role="alert">{{ error }}</p>

      <section class="ws-canvas">
        <RunView v-if="view === 'run'" :key="route.params.run" :name="route.params.run" :theme="theme" />

        <template v-else-if="view === 'home'">
          <div class="ws-hero">
            <div class="ws-orb" aria-hidden="true"></div>
            <h1>{{ greeting }}</h1>
            <h2>What do you want to test before you spend?</h2>
            <p>Ads, prices, pitches, questionnaires, job posts and appeals, on simulated buyers first.</p>
            <div class="ws-composer" style="margin-top: 26px">
              <label class="sr-only" for="ws-home">Describe what you want to test</label>
              <textarea id="ws-home" v-model="idea" rows="2" placeholder="Describe what you want to test, e.g. two headlines for our free trial…" @keydown.enter.exact.prevent="route_"></textarea>
              <div class="ws-composer-row">
                <RouterLink class="ws-chip" to="/workspace/skills">⚡ Skills</RouterLink>
                <RouterLink class="ws-chip" to="/workspace/connectors">⛓ Connectors</RouterLink>
                <RouterLink class="ws-chip" to="/workspace/projects">▦ Open a run</RouterLink>
                <button class="ws-send" :disabled="!idea.trim()" aria-label="Find the right test" @click="route_">↑</button>
              </div>
            </div>
            <div v-if="matches.length" class="ws-cards" style="margin-top: 14px" aria-live="polite">
              <component :is="m.to ? 'RouterLink' : 'button'" v-for="m in matches" :key="m.id" class="ws-card" :to="m.to" :style="{ '--tint': m.tint }" @click="m.to ? null : copy(m.command)">
                <span class="ws-ico">{{ m.icon }}</span><span class="ws-tag">{{ m.tag }}</span>
                <b>{{ m.name }}</b><span>{{ m.to ? m.text : 'Copy: ' + m.command }}</span>
              </component>
            </div>
          </div>
          <div class="ws-section">
            <h3>Start with a skill <small>{{ skills.length }} skills</small></h3>
            <div class="ws-cards">
              <component :is="s.to ? 'RouterLink' : 'button'" v-for="s in skills.slice(0, 3)" :key="s.id" class="ws-card" :to="s.to" :style="{ '--tint': s.tint }" @click="s.to ? null : copy(s.command)">
                <span class="ws-ico">{{ s.icon }}</span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b><span>{{ s.text }}</span>
              </component>
            </div>
            <h3>Recent runs <RouterLink to="/workspace/projects" style="font-size: 12px; color: var(--muted)">All runs</RouterLink></h3>
            <div class="ws-list">
              <RunCard v-for="r in runs.slice(0, 4)" :key="r.name" :run="r" />
            </div>
            <p v-if="!runs.length" class="ws-empty">{{ runsNote }}</p>
          </div>
        </template>

        <div v-else-if="view === 'projects'" class="ws-section" style="padding-top: 24px">
          <h3>Projects <small>{{ filteredRuns.length }} saved runs in {{ root }}</small></h3>
          <div class="ws-list"><RunCard v-for="r in filteredRuns" :key="r.name" :run="r" /></div>
          <p v-if="!filteredRuns.length" class="ws-empty">{{ runsNote }}</p>
        </div>

        <div v-else-if="view === 'skills'" class="ws-section" style="padding-top: 24px">
          <h3>Skills <small>Free ones run on saved files; paid ones call your model provider</small></h3>
          <div class="ws-cards">
            <component :is="s.to ? 'RouterLink' : 'button'" v-for="s in skills" :key="s.id" class="ws-card" :to="s.to" :style="{ '--tint': s.tint }" @click="s.to ? null : copy(s.command)">
              <span class="ws-ico">{{ s.icon }}</span><span class="ws-tag">{{ s.tag }}</span><b>{{ s.name }}</b>
              <span>{{ s.text }}</span>
              <span v-if="s.command" style="display: block; margin-top: 8px; font-family: ui-monospace, monospace; font-size: 11.5px">{{ s.command }}</span>
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
            <button v-for="c in connectors" :key="c.id" class="ws-card" :style="{ '--tint': c.tint }" @click="copy(c.command)">
              <span class="ws-ico">{{ c.icon }}</span><span class="ws-tag">{{ c.tag }}</span><b>{{ c.name }}</b><span>{{ c.text }}</span>
              <span style="display: block; margin-top: 8px; font-family: ui-monospace, monospace; font-size: 11.5px">{{ c.command }}</span>
            </button>
          </div>
          <p class="ws-note">{{ copied || 'Click a connector to copy its command. Agents with a GA4, PostHog, ads or CRM MCP server can pull the data for you.' }}</p>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import RunView from '../components/workspace/RunView.vue'
import { api, token } from '../workspace/api.js'
import '../assets/workspace.css'

const route = useRoute()
const runs = ref([]), root = ref('mirofish_runs'), error = ref(''), search = ref(''), idea = ref(''), copied = ref('')
const provider = ref({ configured: false, models: [] }), menuOpen = ref(false), searchBox = ref(null)
const hasToken = ref(true), loaded = ref(false)
const theme = ref((() => {
  try {
    return localStorage.getItem('mm-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  } catch {
    return 'light'
  }
})())

const view = computed(() => (route.params.run ? 'run' : route.params.page || 'home'))
const crumb = computed(() => (view.value === 'run' ? runs.value.find((r) => r.name === route.params.run)?.title || route.params.run
  : { home: 'Chat', projects: 'Projects', skills: 'Skills', connectors: 'Connectors' }[view.value] || 'Chat'))
const greeting = computed(() => {
  const hr = new Date().getHours()
  return hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening'
})
const filteredRuns = computed(() => {
  const q = search.value.trim().toLowerCase()
  return q ? runs.value.filter((r) => `${r.title} ${r.name}`.toLowerCase().includes(q)) : runs.value
})
const runsNote = computed(() => (!loaded.value ? 'Loading runs…' : 'No saved runs yet. Run a market test, then it shows up here.'))
const providerLine = computed(() => (provider.value.configured ? provider.value.models?.[0]?.model || 'Model connected' : 'No model connected'))
const settingsLink = computed(() => `/setup#t=${encodeURIComponent(token())}`)

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
const connectors = [
  { id: 'ga4', icon: '📈', name: 'Google Analytics 4', tag: 'CSV or MCP', tint: 'rgba(242, 107, 42, 0.14)', command: 'mirofish.py analytics-audience --files ga4.csv', text: 'Size segments from your real audience: countries, channels, devices.' },
  { id: 'posthog', icon: '🦔', name: 'PostHog', tag: 'Export or MCP', tint: 'rgba(217, 162, 59, 0.16)', command: 'mirofish.py analytics-audience --files posthog.json', text: 'Persons and events exports become segment shares and population weights.' },
  { id: 'ads', icon: '📣', name: 'Ad accounts', tag: 'CSV', tint: 'rgba(79, 124, 214, 0.14)', command: 'mirofish.py ads-import export.csv --out scenarios/x/past_ads.md', text: 'Past ads from Meta, Google or TikTok as benchmarks and seed.' },
  { id: 'crm', icon: '👥', name: 'Customers and reviews', tag: 'CSV / text', tint: 'rgba(31, 107, 79, 0.14)', command: 'mirofish.py intake --files reviews.csv calls/*.txt --out scenarios/x/personas.json', text: 'Your own customers become grounded personas. Contact details are removed locally.' },
  { id: 'real', icon: '✓', name: 'Real answers', tag: 'CSV', tint: 'rgba(122, 139, 47, 0.16)', command: 'mirofish.py calibrate --run-dir mirofish_runs/<run> --real answers.csv', text: 'Answers from real people to check the simulated ones.' },
  { id: 'agents', icon: '✦', name: 'Claude Code, Codex, Gemini', tag: 'MCP', tint: 'rgba(162, 89, 196, 0.14)', command: '/plugin install market-mirror', text: 'Run every skill from your agent; it can pull data from its own connectors.' }
]

const matches = ref([])
function route_() {
  const text = idea.value.trim()
  if (!text) return
  const hit = skills.filter((s) => s.words.test(text))
  matches.value = (hit.length ? hit : skills.slice(0, 3)).slice(0, 3)
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
  }
}

onMounted(async () => {
  document.addEventListener('keydown', onSlash)
  hasToken.value = !!token()
  if (!hasToken.value) return
  try {
    const [list, meta] = await Promise.all([api('/api/runs'), api('/api/workflows/meta').catch(() => null)])
    runs.value = list.runs
    root.value = list.root.split('/').slice(-1)[0]
    if (meta?.provider) provider.value = meta.provider
  } catch (e) {
    error.value = e.message
  } finally {
    loaded.value = true
  }
})
onUnmounted(() => document.removeEventListener('keydown', onSlash))

const RunCard = defineComponent({
  props: { run: { type: Object, required: true } },
  setup(p) {
    const when = (x) => {
      try {
        return new Date(x).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
      } catch {
        return ''
      }
    }
    return () => h(RouterLink, { to: `/workspace/runs/${p.run.name}`, class: 'ws-card', style: { '--tint': 'rgba(31, 107, 79, 0.1)' } }, () => [
      h('span', { class: 'ws-ico' }, '▦'),
      p.run.decision ? h('span', { class: `ws-tag pill ${String(p.run.decision).toLowerCase().replace(' ', '-')}` }, String(p.run.decision).toUpperCase()) : null,
      h('b', p.run.title),
      h('span', [p.run.people ? `${p.run.people} simulated people · ` : '', when(p.run.updated_at || p.run.mtime * 1000)].join(''))
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
