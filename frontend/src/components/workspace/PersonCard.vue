<template>
  <article class="ws-person" :aria-labelledby="`ws-person-${person.agent_id}`">
    <header class="ws-person-head">
      <span class="ws-person-av" :style="{ background: color }" aria-hidden="true">{{ initials }}</span>
      <div>
        <h3 :id="`ws-person-${person.agent_id}`">{{ person.name || `Person ${person.agent_id}` }}</h3>
        <p>{{ subtitle }}</p>
        <span v-if="person.segment" class="ws-tagx" :style="{ color, borderColor: color }">{{ person.segment }}</span>
      </div>
      <button type="button" class="ws-icon-btn" aria-label="Close this person" @click="$emit('close')"><Ico name="x" /></button>
    </header>

    <p v-if="account" class="ws-person-account"><Ico name="users" :size="14" />{{ account }} in the simulation. It posts and replies like a person but is not a buyer, so it was not asked whether it would buy.</p>
    <section v-if="!account" class="ws-person-verdict" :class="verdict ? verdict.tone : 'none'">
      <small>Would they buy?</small>
      <b>{{ verdict ? verdict.label : 'Not asked' }}</b>
      <span>{{ verdict ? verdict.note : 'This person did not answer the buyer survey in this run.' }}</span>
      <div v-if="scores.length" class="ws-person-scores">
        <span v-for="sc in scores" :key="sc.label">{{ sc.label }} <b>{{ sc.value }}</b>/10</span>
      </div>
    </section>

    <section v-if="answer?.quote" class="ws-person-block">
      <h4><Ico name="chat" :size="14" />In their own words</h4>
      <blockquote>“{{ answer.quote }}”</blockquote>
    </section>
    <section v-if="answer?.main_objection" class="ws-person-block warn">
      <h4><Ico name="no" :size="14" />What’s holding them back</h4>
      <p>{{ answer.main_objection }}</p>
    </section>
    <section v-if="answer?.would_change_mind" class="ws-person-block good">
      <h4><Ico name="idea" :size="14" />What would change their mind</h4>
      <p>{{ answer.would_change_mind }}</p>
    </section>

    <section class="ws-person-block">
      <h4><Ico name="activity" :size="14" />What they did in the simulation</h4>
      <p>{{ activityLine }}</p>
      <ul v-if="talkedTo.length" class="ws-person-links">
        <li v-for="t in talkedTo" :key="t.label"><Ico :name="t.icon" :size="13" />{{ t.label }}</li>
      </ul>
    </section>

    <section class="ws-person-block">
      <h4><Ico name="user" :size="14" />About them</h4>
      <dl>
        <template v-for="f in facts" :key="f.label"><dt>{{ f.label }}</dt><dd>{{ f.value }}</dd></template>
      </dl>
    </section>

    <section v-if="thoughts.length" class="ws-person-block">
      <h4><Ico name="brain" :size="14" />Their thinking, step by step</h4>
      <ol class="ws-person-thoughts">
        <li v-for="(t, i) in shownThoughts" :key="i">
          <small>{{ plainSource(t) }}</small>
          <p>{{ t.text }}</p>
          <em v-if="t.did">{{ plainDid(t.did) }}</em>
        </li>
      </ol>
      <button v-if="thoughts.length > 4" type="button" class="ws-link-btn" @click="allThoughts = !allThoughts">
        {{ allThoughts ? 'Show fewer' : `Show all ${thoughts.length}` }}
      </button>
    </section>

    <details v-if="person.interview_summary" class="ws-person-block">
      <summary>Their background, in their words</summary>
      <p>{{ person.interview_summary }}</p>
    </details>

    <footer class="ws-person-foot">
      <button type="button" class="ws-btn primary" @click="$emit('ask', person.agent_id)">
        <Ico name="chat" :size="14" />Ask {{ account ? 'this account' : firstName }} a question<span class="ws-paid" title="Sends one model call">$</span>
      </button>
      <p><Ico name="shield" :size="12" />An invented person. Every answer was written by an AI model playing them. No real person is represented.</p>
    </footer>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import Ico from './Ico.vue'
import { describeActivity, plainDid, verdictOf } from '../../workspace/runActivity.js'

const props = defineProps({
  person: { type: Object, required: true },
  color: { type: String, default: '#5fc79a' },
  answer: { type: Object, default: null },
  stats: { type: Object, default: null },
  thoughts: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  names: { type: Object, default: () => ({}) }
})
defineEmits(['close', 'ask'])
const allThoughts = ref(false)

const list = (v) => {
  if (Array.isArray(v)) return v.join(', ')
  const s = String(v ?? '').trim()
  if (s.startsWith('[')) {
    try {
      return JSON.parse(s.replace(/'/g, '"')).join(', ')
    } catch {
      return s.replace(/[[\]']/g, '')
    }
  }
  return s
}
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const account = computed(() => (props.person.kind && props.person.kind !== 'persona' ? (props.person.kind === 'community' ? 'A community account' : 'A brand or market account') : ''))
const firstName = computed(() => String(props.person.name || 'this person').split(' ')[0])
const initials = computed(() => String(props.person.name || '?').split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase())
const subtitle = computed(() => {
  const p = props.person
  const where = [p.city, p.country].filter(Boolean).join(', ')
  if (account.value) return [account.value, where].filter(Boolean).join(' · ')
  return [p.age ? `${p.age} years old` : '', p.occupation, where].filter(Boolean).join(' · ')
})
const verdict = computed(() => verdictOf(props.answer?.would_convert))
const scores = computed(() => {
  const a = props.answer || {}
  return [['Interest', a.interest], ['Trust', a.trust], ['Would recommend', a.recommend]]
    .filter(([, v]) => typeof v === 'number').map(([label, v]) => ({ label, value: Math.round(v * 10) / 10 }))
})
const activityLine = computed(() => (props.stats ? describeActivity(props.stats) : 'No social activity was recorded for this person.'))
const talkedTo = computed(() => {
  const id = String(props.person.agent_id)
  const name = (x) => props.names[String(x)] || `Person ${x}`
  const out = []
  const mine = props.edges.filter((e) => String(e.from) === id)
  const toMe = props.edges.filter((e) => String(e.to) === id)
  const group = (es, key) => [...new Set(es.map((e) => (e[key] === null ? 'the brand' : name(e[key]))))]
  const say = (verb, es, key, icon) => {
    if (!es.length) return
    const who = group(es, key)
    out.push({ icon, label: `${verb} ${who.slice(0, 3).join(', ')}${who.length > 3 ? ` and ${who.length - 3} more` : ''}` })
  }
  say('Replied to', mine.filter((e) => e.kind === 'reply'), 'to', 'chat')
  say('Liked posts by', mine.filter((e) => e.kind === 'like'), 'to', 'star')
  say('Quoted', mine.filter((e) => e.kind === 'quote'), 'to', 'refresh')
  say('Got replies from', toMe.filter((e) => e.kind === 'reply'), 'from', 'chats')
  say('Liked by', toMe.filter((e) => e.kind === 'like'), 'from', 'users')
  return out
})
const facts = computed(() => {
  const p = props.person
  return [
    ['Job', p.occupation], ['Income', p.income_level && `${cap(String(p.income_level).replace(/[-_]/g, ' '))} income`],
    ['Speaks', list(p.languages)], ['How they decide', p.decision_role], ['Where they spend time online', p.platform_habits || p.media_diet],
    ['Phone and data', [p.phone, p.data_plan].filter(Boolean).join(' · ')], ['Comfort with tech', p.tech_comfort && cap(p.tech_comfort)],
    ['How they think', p.thinking_style && cap(p.thinking_style)], ['Groups they belong to', list(p.communities)]
  ].filter(([, v]) => v && String(v).trim()).map(([label, value]) => ({ label, value: String(value) }))
})
const plainSource = (t) => {
  const s = String(t.source || '')
  if (s === 'ad in feed') return `Saw an ad${t.context ? ` (${t.context})` : ''}`
  if (s === 'landing page') return 'Opened the landing page'
  if (s === 'survey') return 'Answered the buyer survey'
  if (s === 'sales pitch') return 'Heard the sales pitch'
  if (s === 'social feed') return `Wrote on social media${t.context ? ` (${String(t.context).replace(/^twitter/i, 'Twitter-style,').replace(/^reddit/i, 'Reddit-style,')})` : ''}`
  if (s === 'thought_test') return 'Private thought'
  return cap(s) || 'Recorded'
}
const shownThoughts = computed(() => (allThoughts.value ? props.thoughts : props.thoughts.slice(0, 4)))
</script>
