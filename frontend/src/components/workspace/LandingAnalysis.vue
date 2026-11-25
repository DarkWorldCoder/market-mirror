<template>
  <section class="la" :class="{ compact }" :aria-labelledby="`${uid}-title`">
    <header class="la-head">
      <component :is="h" :id="`${uid}-title`" class="la-title"><PanelTop :size="16" aria-hidden="true" />Landing page analysis</component>
      <span class="la-sim">Simulated</span>
    </header>

    <LoadingSkeleton v-if="loading" :lines="4" label="Loading the landing page results" />

    <p v-else-if="!a.hasData && error" class="la-note" role="alert">{{ error }}</p>

    <div v-else-if="!a.hasData" class="la-empty">
      <p>This run has no landing page results yet. A landing or website test sends the simulated buyers from the ad to your page and records where they leave and why.</p>
      <button type="button" class="la-chip" @click="prompt(landingTestPrompt(run), false)"><Globe :size="14" aria-hidden="true" />Test a landing page</button>
      <p class="la-note">This only fills in the chat box. Nothing runs until you send it and approve the cost.</p>
    </div>

    <template v-else>
      <p class="la-lede">{{ lede }}</p>
      <p v-if="error" class="la-note" role="status">{{ error }}</p>

      <!-- 1. Funnel -->
      <section v-for="f in funnels" :key="f.id" class="la-block" :aria-labelledby="`${uid}-${f.id}`">
        <component :is="h2" :id="`${uid}-${f.id}`" class="la-sub"><Filter :size="14" aria-hidden="true" />{{ f.title }}</component>
        <p v-if="f.lede" class="la-note">{{ f.lede }}</p>
        <ol class="la-funnel" :aria-label="`${f.title}, simulated counts`">
          <li v-for="(s, i) in f.data.steps" :key="s.key" :class="{ first: i === 0 }">
            <span class="la-step">{{ s.label }}</span>
            <b class="la-n">{{ fmt(s.n) }}</b>
            <template v-if="f.data.ordered && i > 0">
              <span class="la-keep" aria-hidden="true"><i :style="{ width: `${Math.max(s.n ? 3 : 0, s.keptPct || 0)}%` }"></i></span>
              <small class="la-drop" :class="{ steep: s.dropPct >= 50 }">{{ s.keptPct }}% kept<template v-if="s.lost"> · {{ fmt(s.lost) }} left</template></small>
            </template>
            <small v-else-if="f.data.ordered" class="la-drop">start</small>
          </li>
        </ol>
        <p class="la-note">{{ [f.data.basis, f.small, 'Simulated, not real visitors.'].filter(Boolean).join(' ') }}</p>
      </section>

      <!-- 2. Where and why people left -->
      <section v-for="c in causeBlocks" :key="c.id" class="la-block" :aria-labelledby="`${uid}-${c.id}`">
        <component :is="h2" :id="`${uid}-${c.id}`" class="la-sub"><LogOut :size="14" aria-hidden="true" />{{ c.title }}</component>
        <ul v-if="c.data.stages.length" class="la-stages" aria-label="Where they left">
          <li v-for="st in c.data.stages" :key="st.key"><b>{{ fmt(st.n) }}</b> {{ st.label.toLowerCase() }}</li>
        </ul>
        <ol v-if="c.data.causes.length" class="la-causes">
          <li v-for="(cause, i) in c.data.causes" :key="cause.key">
            <div class="la-cause-head">
              <span class="la-rank" aria-hidden="true">{{ i + 1 }}</span>
              <b>{{ cause.label }}</b>
              <span class="la-share">{{ cause.count }} of {{ c.data.total }} · {{ cause.sharePct }}%</span>
            </div>
            <span class="la-bar" aria-hidden="true"><i :style="{ width: `${cause.sharePct}%` }"></i></span>
            <blockquote v-for="q in cause.quotes" :key="q.text" class="la-quote">
              <p><span v-if="q.kind === 'thought'" class="la-qkind">Their thought on the page: </span>“{{ q.text }}”</p>
              <cite v-if="q.who">{{ q.who }}</cite>
            </blockquote>
            <p v-for="e in cause.events" :key="e" class="la-event">Recorded: {{ e }}</p>
          </li>
        </ol>
        <p class="la-note">{{ c.data.note }}</p>
      </section>

      <!-- 3. Per-ad comparison -->
      <section v-if="a.ads" class="la-block" :aria-labelledby="`${uid}-ads`">
        <component :is="h2" :id="`${uid}-ads`" class="la-sub"><Megaphone :size="14" aria-hidden="true" />Which ad sent the people who went furthest</component>
        <p class="la-lead-text"><Award v-if="a.ads.leader" :size="14" aria-hidden="true" />{{ a.ads.leaderText }}</p>
        <ul class="la-ads">
          <li v-for="r in a.ads.rows" :key="r.id" :class="{ leader: r.id === a.ads.leader }">
            <div class="la-ad-name"><b>{{ r.name }}</b><small v-if="r.platform">{{ r.platform }}</small><span v-if="r.id === a.ads.leader" class="la-badge">Furthest</span></div>
            <dl class="la-ad-steps">
              <div><dt>Clicked</dt><dd>{{ fmt(r.clicks) }}</dd></div>
              <div><dt>Page loaded</dt><dd>{{ fmt(r.loaded) }}</dd></div>
              <div v-if="r.read != null"><dt>Read</dt><dd>{{ fmt(r.read) }}</dd></div>
              <div><dt>Started signup</dt><dd>{{ fmt(r.started) }}</dd></div>
              <div><dt>Converted</dt><dd>{{ fmt(r.converted) }}<small v-if="r.convertedPct != null"> · {{ r.convertedPct }}%</small></dd></div>
            </dl>
          </li>
        </ul>
        <p class="la-note">{{ a.ads.note }}</p>
      </section>

      <!-- 4. Section by section -->
      <section v-if="outlines.length" class="la-block" :aria-labelledby="`${uid}-outline`">
        <component :is="h2" :id="`${uid}-outline`" class="la-sub"><LayoutList :size="14" aria-hidden="true" />Section by section</component>
        <div v-for="o in outlines" :key="o.id" class="la-outline-wrap">
          <p class="la-outline-title">{{ o.title }}</p>
          <ol class="la-outline">
            <li v-for="s in o.sections" :key="s.key">
              <div class="la-out-head">
                <b>{{ s.title }}</b>
                <small v-if="s.where" class="la-where">{{ s.where }} of the page</small>
                <span class="la-out-n">{{ s.reachedText }}</span>
              </div>
              <span class="la-bar" aria-hidden="true"><i :style="{ width: `${s.barPct}%` }"></i></span>
              <p v-if="s.detail" class="la-out-detail">{{ s.detail }}</p>
              <p v-if="s.mark" class="la-out-mark" :class="{ steep: s.steep }"><TrendingDown :size="13" aria-hidden="true" />{{ s.mark }}</p>
              <p v-if="s.warning" class="la-out-detail muted">Lab note: {{ s.warning }}</p>
            </li>
          </ol>
          <p class="la-note">{{ o.note }}</p>
        </div>
      </section>

      <!-- 5. What to fix first -->
      <section v-if="a.fixes.length" class="la-block" :aria-labelledby="`${uid}-fixes`">
        <component :is="h2" :id="`${uid}-fixes`" class="la-sub"><Wrench :size="14" aria-hidden="true" />What to fix first</component>
        <p class="la-note">Ordered by the size of each saved estimate. The estimates use different measures, so treat the order as rough. All simulated.</p>
        <ol class="la-fixes">
          <li v-for="(f, i) in shownFixes" :key="f.id">
            <div class="la-fix-head">
              <span class="la-rank" aria-hidden="true">{{ i + 1 }}</span>
              <b>{{ f.title }}</b>
              <span class="la-source">{{ f.source }}</span>
            </div>
            <dl v-if="f.before || f.after" class="la-change">
              <div v-if="f.before"><dt>Now</dt><dd>{{ f.before }}</dd></div>
              <div v-if="f.after"><dt>Try</dt><dd>{{ f.after }}</dd></div>
            </dl>
            <p v-if="f.estimate" class="la-est" :class="f.good === true ? 'good' : f.good === false ? 'bad' : ''">
              <TrendingUp v-if="f.estimate.direction === 'up'" :size="14" aria-hidden="true" />
              <TrendingDown v-else-if="f.estimate.direction === 'down'" :size="14" aria-hidden="true" />
              <span>Expected: {{ f.estimate.text }}<template v-if="f.good === true"> (better)</template><template v-else-if="f.good === false"> (worse)</template> · simulated estimate</span>
            </p>
            <p v-else class="la-est">No size estimate saved for this one.</p>
            <ul class="la-evidence">
              <li v-for="e in f.evidence" :key="e">{{ e }}</li>
            </ul>
            <blockquote v-for="q in f.quotes || []" :key="q" class="la-quote"><p>“{{ q }}”</p></blockquote>
            <button type="button" class="la-chip" @click="prompt(fixPrompt(f, run), true)"><MessageSquarePlus :size="14" aria-hidden="true" />Ask the chat to test this fix</button>
          </li>
        </ol>
        <button v-if="a.fixes.length > fixLimit" type="button" class="la-more" :aria-expanded="allFixes" @click="allFixes = !allFixes">{{ allFixes ? 'Show fewer' : `Show ${a.fixes.length - fixLimit} more` }}</button>
        <p class="la-note">{{ askNote }}</p>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, useId, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Award, Filter, Globe, LayoutList, LogOut, Megaphone, MessageSquarePlus, PanelTop, TrendingDown, TrendingUp, Wrench } from 'lucide-vue-next'
import LoadingSkeleton from './LoadingSkeleton.vue'
import { api } from '../../workspace/api.js'
import { fixPrompt, landingAnalysis, landingTestPrompt } from '../../workspace/landingAnalysis.js'

const props = defineProps({
  name: { type: String, required: true },
  files: { type: Array, default: () => [] },
  // the run page already holds feed_test.json; leave it out and this section reads it itself
  feed: { type: Object, default: undefined },
  title: { type: String, default: '' },
  compact: { type: Boolean, default: false },
  level: { type: Number, default: 3 },
  // @prompt from the chat card; without it the prompt opens the chat with the text filled in
  onPrompt: { type: Function, default: null }
})
const router = useRouter()
const uid = useId()
const h = computed(() => `h${Math.min(6, props.level)}`)
const h2 = computed(() => `h${Math.min(6, props.level + 1)}`)
const loading = ref(false), error = ref('')
const loaded = ref({})
const allFixes = ref(false)
const fixLimit = computed(() => (props.compact ? 3 : 5))
const run = computed(() => ({ name: props.name, title: props.title || props.name }))
const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('en-US') : '–')

const want = computed(() => {
  const have = new Set(props.files || [])
  const list = ['cro_lab.json', 'landing_teardown.json', 'causal_whatif.json', 'website_test.json'].filter((f) => have.has(f))
  if (props.feed === undefined && have.has('feed_test.json')) list.push('feed_test.json')
  return list
})
let ticket = 0
async function load() {
  const mine = ++ticket, files = want.value
  const missing = files.filter((f) => !(f in loaded.value))
  // Nothing to read for this run: end any skeleton an earlier run's read left on (its ticket is now stale).
  if (!missing.length) { loading.value = false; return }
  loading.value = !Object.keys(loaded.value).length
  const next = { ...loaded.value }, failed = []
  await Promise.all(missing.map(async (f) => {
    try { next[f] = await api(`/api/runs/${encodeURIComponent(props.name)}/files/${f}`) } catch { next[f] = null; failed.push(f) }
  }))
  if (mine !== ticket) return
  loaded.value = next
  const anyRead = Object.values(next).some((value) => value != null)
  error.value = !failed.length ? '' : anyRead ? `Could not read ${failed.join(', ')}; the rest is shown.` : `Could not read ${failed.join(', ')}. Try again in a moment.`
  loading.value = false
}
watch(() => props.name, () => { loaded.value = {}; allFixes.value = false; load() })
watch(want, load, { immediate: true })

const a = computed(() => landingAnalysis({
  feed: props.feed === undefined ? loaded.value['feed_test.json'] : props.feed,
  cro: loaded.value['cro_lab.json'],
  teardown: loaded.value['landing_teardown.json'],
  whatif: loaded.value['causal_whatif.json'],
  web: loaded.value['website_test.json']
}))

const funnels = computed(() => {
  const out = []
  const f = a.value.funnel
  if (f) {
    const clicked = f.steps.find((s) => s.key === 'clicked')?.n
    out.push({ id: 'funnel', title: 'From the ad to the signup', data: f,
      small: clicked != null && clicked < 30 ? `Only ${fmt(clicked)} people clicked, so read the page steps as a handful of stories, not rates.` : '' })
  }
  const w = a.value.webFunnel
  if (w) out.push({ id: 'webfunnel', title: 'Website journey', data: w, lede: [a.value.website?.goal && `Goal: ${a.value.website.goal.replace(/_/g, ' ')}`, a.value.website?.url].filter(Boolean).join(' · '), small: '' })
  return out
})
const causeBlocks = computed(() => [
  a.value.causes && { id: 'why', title: `Where and why people left${a.value.causes.left ? ` (${fmt(a.value.causes.left)} who clicked but did not convert)` : ''}`, data: a.value.causes },
  a.value.webCauses && { id: 'webwhy', title: 'How the website visits ended', data: a.value.webCauses }
].filter(Boolean))

const outlines = computed(() => {
  const out = []
  const p = a.value.outline.page
  if (p) {
    out.push({ id: 'page', title: 'The page, as the simulated clickers met it', note: `${p.note} Simulated.`,
      sections: p.sections.map((s) => ({
        key: s.key, title: s.title, detail: s.detail, barPct: s.reachedPct || 0,
        reachedText: `${fmt(s.reached)} reached${s.reachedPct != null ? ` · ${s.reachedPct}%` : ''}`,
        mark: s.left ? `${fmt(s.left)} left here${s.key === 'form' && s.finished != null ? `, ${fmt(s.finished)} finished` : ''}` : s.key === 'form' && s.finished != null ? `${fmt(s.finished)} finished` : '',
        steep: s.reached ? s.left / s.reached >= 0.5 : false
      }))
    })
  }
  const sc = a.value.outline.scroll
  if (sc) {
    out.push({ id: 'scroll', title: sc.kind === 'zones' ? 'Scroll test: share still reading at each part' : 'How far people said they would read', note: sc.note,
      sections: sc.sections.map((s) => ({
        key: s.key, title: s.title, where: s.where, detail: s.detail, warning: s.warning, barPct: s.keptPct || 0,
        reachedText: s.keptPct != null ? `${s.keptPct}% still reading` : '',
        mark: s.dropPts ? `${s.dropPts} pts stopped before this part` : '', steep: (s.dropPts || 0) >= 20
      }))
    })
  }
  const pg = a.value.outline.pages
  if (pg) {
    out.push({ id: 'pages', title: 'Pages the website visitors reached', note: `Out of ${pg.visitors} synthetic visitors. Simulated browser journeys.`,
      sections: pg.sections.map((s) => ({ key: s.key, title: s.title, detail: s.path && s.path !== '/' ? s.path : s.url, barPct: s.reachedPct || 0, reachedText: `${s.reached} reached`, mark: '' }))
    })
  }
  return out
})

const lede = computed(() => (a.value.funnel || a.value.fixes.length
  ? 'How the simulated people went from the ad to the page and the signup, where they left, and what the run suggests fixing first.'
  : 'How the synthetic visitors moved through the website, which checks passed and how each visit ended.'))
const shownFixes = computed(() => (allFixes.value ? a.value.fixes : a.value.fixes.slice(0, fixLimit.value)))
const askNote = computed(() => (props.onPrompt
  ? 'Testing a fix goes to the chat agent. It shows the cost on an approval card, and nothing runs until you approve it.'
  : 'Testing a fix opens the chat with the request filled in. Nothing runs until you send it and approve the cost.'))

function prompt(text, send) {
  if (props.onPrompt) props.onPrompt({ text, send, run: props.name })
  else router.push({ path: '/', query: { prompt: text } })
}
</script>
