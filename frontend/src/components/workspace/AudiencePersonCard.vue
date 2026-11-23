<template>
  <article class="apc" :aria-labelledby="`apc-${person.agent_id}`">
    <header class="apc-head">
      <span class="apc-avatar" :style="{ background: color }" aria-hidden="true">{{ initials }}</span>
      <div class="apc-who">
        <h4 :id="`apc-${person.agent_id}`">{{ person.name || `Person ${person.agent_id}` }}</h4>
        <p>{{ subtitle }}</p>
        <span class="apc-chips">
          <span class="apc-sim">{{ account ? 'Simulated account' : 'Simulated person' }}</span>
          <span v-if="person.segment && !account" class="apc-chip" :style="{ color, borderColor: color }">{{ person.segment }}</span>
        </span>
      </div>
    </header>

    <p v-if="account" class="apc-account"><UsersRound :size="15" aria-hidden="true" />{{ account }} in the simulation. It posts and replies like a person but is not a buyer, so it was not asked whether it would buy.</p>

    <section v-else class="apc-verdict" :class="verdict ? verdict.tone : 'none'">
      <small>Would they buy? · simulated answer</small>
      <strong>{{ verdict ? verdict.label : 'Not asked' }}</strong>
      <span>{{ verdict ? verdict.note : 'This person did not answer the buyer survey in this run.' }}</span>
      <div v-if="scores.length" class="apc-scores">
        <span v-for="s in scores" :key="s.label">{{ s.label }} <b>{{ s.value }}</b>/10</span>
      </div>
    </section>

    <section v-if="answer?.quote" class="apc-block">
      <h5><MessageSquareQuote :size="14" aria-hidden="true" />In their own words</h5>
      <blockquote>“{{ answer.quote }}”</blockquote>
    </section>
    <section v-if="answer?.main_objection" class="apc-block apc-warn">
      <h5><ThumbsDown :size="14" aria-hidden="true" />What’s holding them back</h5>
      <p>{{ answer.main_objection }}</p>
    </section>
    <section v-if="answer?.would_change_mind" class="apc-block apc-good">
      <h5><Lightbulb :size="14" aria-hidden="true" />What would change their mind</h5>
      <p>{{ answer.would_change_mind }}</p>
    </section>

    <section class="apc-block">
      <h5><Activity :size="14" aria-hidden="true" />What they did in the simulation</h5>
      <p>{{ activityLine }}</p>
      <ul v-if="talkedTo.length" class="apc-links">
        <li v-for="t in talkedTo" :key="t.label"><component :is="t.icon" :size="13" aria-hidden="true" />{{ t.label }}</li>
      </ul>
    </section>

    <section v-if="facts.length" class="apc-block">
      <h5><UserRound :size="14" aria-hidden="true" />About them</h5>
      <dl class="apc-facts">
        <div v-for="f in facts" :key="f.label"><dt>{{ f.label }}</dt><dd>{{ f.value }}</dd></div>
      </dl>
    </section>

    <section v-if="thoughts.length" class="apc-block">
      <h5><Brain :size="14" aria-hidden="true" />Their thinking, step by step</h5>
      <ol class="apc-thoughts">
        <li v-for="(t, i) in shownThoughts" :key="i">
          <small>{{ plainSource(t) }}</small>
          <p>{{ t.text }}</p>
          <em v-if="t.did">{{ plainDid(t.did) }}</em>
        </li>
      </ol>
      <button v-if="thoughts.length > 4" type="button" class="apc-more" @click="all = !all">{{ all ? 'Show fewer' : `Show all ${thoughts.length}` }}</button>
    </section>

    <details v-if="person.interview_summary" class="apc-block apc-background">
      <summary>Their background, in their words</summary>
      <p>{{ person.interview_summary }}</p>
    </details>

    <RouterLink v-if="askTo && !account" class="apc-ask" :to="askTo"><MessageCircle :size="14" aria-hidden="true" />Ask {{ String(person.name || 'this person').split(' ')[0] }} a question<span class="apc-paid" title="Sends one model call when you press send">$</span></RouterLink>
    <p class="apc-foot"><ShieldCheck :size="13" aria-hidden="true" />An invented person. Every answer was written by an AI model playing them. No real person is represented.</p>
  </article>
</template>

<script setup>
// A simulated person in plain words: their verdict first, then their own words, what holds them back, what would change
// their mind, what they did and with whom, facts about them and their recorded thinking.
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Activity, Brain, Heart, Lightbulb, MessageCircle, MessageSquareQuote, MessagesSquare, Repeat2, ShieldCheck, ThumbsDown, UserRound, UsersRound } from 'lucide-vue-next'
import { describeActivity, plainDid, verdictOf } from '../../workspace/runActivity'

const props = defineProps({
  askTo: { type: Object, default: null },
  person: { type: Object, required: true },
  color: { type: String, default: '#25785d' },
  answer: { type: Object, default: null },
  stats: { type: Object, default: null },
  thoughts: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  names: { type: Object, default: () => ({}) }
})
const all = ref(false)

const list = (v) => {
  if (Array.isArray(v)) return v.join(', ')
  const s = String(v ?? '').trim()
  if (s.startsWith('[')) {
    try { return JSON.parse(s.replace(/'/g, '"')).join(', ') } catch { return s.replace(/[[\]']/g, '') }
  }
  return s
}
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const account = computed(() => (props.person.kind && props.person.kind !== 'persona' ? (props.person.kind === 'community' ? 'A community account' : 'A brand or market account') : ''))
const initials = computed(() => String(props.person.name || '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase())
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
  const name = (x) => (x === null || x === undefined ? 'the brand' : props.names[String(x)] || `Person ${x}`)
  const mine = props.edges.filter((e) => String(e.from) === id), toMe = props.edges.filter((e) => String(e.to) === id)
  const out = []
  const say = (verb, es, key, icon) => {
    if (!es.length) return
    const who = [...new Set(es.map((e) => name(e[key])))]
    out.push({ icon, label: `${verb} ${who.slice(0, 3).join(', ')}${who.length > 3 ? ` and ${who.length - 3} more` : ''}` })
  }
  say('Replied to', mine.filter((e) => e.kind === 'reply'), 'to', MessageCircle)
  say('Liked posts by', mine.filter((e) => e.kind === 'like'), 'to', Heart)
  say('Quoted or shared', mine.filter((e) => e.kind === 'quote'), 'to', Repeat2)
  say('Got replies from', toMe.filter((e) => e.kind === 'reply'), 'from', MessagesSquare)
  say('Liked by', toMe.filter((e) => e.kind === 'like'), 'from', UsersRound)
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
  const ctx = String(t.context || '').replace(/^twitter/i, 'Twitter-style,').replace(/^reddit/i, 'Reddit-style,')
  if (s === 'ad in feed') return `Saw an ad${ctx ? ` (${ctx})` : ''}`
  if (s === 'landing page') return 'Opened the landing page'
  if (s === 'survey') return 'Answered the buyer survey'
  if (s === 'sales pitch') return 'Heard the sales pitch'
  if (s === 'social feed') return `Wrote on social media${ctx ? ` (${ctx})` : ''}`
  if (s === 'thought_test') return 'Private thought'
  return cap(s) || 'Recorded'
}
const shownThoughts = computed(() => (all.value ? props.thoughts : props.thoughts.slice(0, 4)))
</script>

<style scoped>
.apc { margin-top: 14px; padding: 16px; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); font-size: 13px; line-height: 1.55; min-width: 0; }
.apc-head { display: flex; gap: 12px; align-items: flex-start; }
.apc-avatar { width: 42px; height: 42px; flex: 0 0 42px; border-radius: 12px; display: grid; place-items: center; color: #fff; font-weight: 650; font-size: 14px; }
.apc-who { min-width: 0; }
.apc-who h4 { font-size: 15px; font-weight: 600; margin: 0; }
.apc-who p { color: var(--muted); font-size: 12px; margin: 2px 0 6px; overflow-wrap: anywhere; }
.apc-chip { display: inline-block; font-size: 11px; border: 1px solid; border-radius: 999px; padding: 0 8px; }
.apc-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.apc-sim { display: inline-block; font-size: 11px; color: var(--muted); border: 1px dashed var(--line); border-radius: 999px; padding: 0 8px; }
.apc-account { display: flex; gap: 7px; margin: 12px 0 0; padding: 10px 12px; border: 1px dashed var(--line); border-radius: 10px; background: var(--panel-2); color: var(--muted); font-size: 12px; }
.apc-verdict { margin-top: 14px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; display: flex; flex-direction: column; gap: 2px; }
.apc-verdict small { font-size: 10.5px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--muted); }
.apc-verdict strong { font-size: 24px; line-height: 1.15; font-weight: 700; }
.apc-verdict span { font-size: 12px; color: var(--muted); }
.apc-verdict.yes { background: color-mix(in srgb, #2f8f5b 11%, transparent); border-color: color-mix(in srgb, #2f8f5b 40%, var(--line)); }
.apc-verdict.yes strong { color: #2f8f5b; }
.apc-verdict.maybe { background: color-mix(in srgb, #c28a1e 11%, transparent); border-color: color-mix(in srgb, #c28a1e 40%, var(--line)); }
.apc-verdict.maybe strong { color: #b07a12; }
.apc-verdict.no { background: color-mix(in srgb, #c8584b 11%, transparent); border-color: color-mix(in srgb, #c8584b 40%, var(--line)); }
.apc-verdict.no strong { color: #c0483b; }
.apc-scores { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 6px; font-size: 12px; color: var(--muted); }
.apc-scores b { color: var(--text); }
.apc-block { margin-top: 14px; }
.apc-block h5 { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--muted); margin: 0 0 5px; }
.apc-block p { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.apc-block blockquote { margin: 0; padding: 8px 12px; border-left: 3px solid var(--accent, #25785d); border-radius: 6px; background: var(--panel-2); font-style: italic; overflow-wrap: anywhere; }
.apc-warn p { padding: 8px 12px; border-radius: 8px; background: color-mix(in srgb, #c8584b 8%, transparent); }
.apc-good p { padding: 8px 12px; border-radius: 8px; background: color-mix(in srgb, #2f8f5b 8%, transparent); }
.apc-links { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 4px; }
.apc-links li { display: flex; align-items: center; gap: 6px; font-size: 12.5px; }
.apc-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 0; }
.apc-facts > div { padding: 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel-2); min-width: 0; }
.apc-facts dt { font-size: 11px; color: var(--muted); margin: 0 0 2px; }
.apc-facts dd { margin: 0; font-size: 12.5px; overflow-wrap: anywhere; }
.apc-thoughts { list-style: none; margin: 0; padding: 0; }
.apc-thoughts li { border-left: 2px solid var(--line); padding: 2px 0 9px 10px; }
.apc-thoughts small { font-size: 11px; color: var(--muted); }
.apc-thoughts em { display: block; font-style: normal; font-size: 11.5px; color: var(--muted); }
.apc-more { border: 0; background: none; padding: 4px 0; color: var(--accent, #25785d); cursor: pointer; font-size: 12.5px; }
.apc-background summary { cursor: pointer; font-size: 12px; font-weight: 600; color: var(--muted); }
.apc-background p { margin-top: 6px; }
.apc-foot { display: flex; gap: 6px; align-items: flex-start; margin: 16px 0 0; font-size: 11.5px; color: var(--muted); }
@media (max-width: 500px) { .apc-facts { grid-template-columns: 1fr; } }
.apc-ask{display:inline-flex;align-items:center;gap:7px;margin-top:14px;padding:8px 13px;border-radius:10px;background:var(--text);color:var(--panel);font-size:13px;font-weight:550;text-decoration:none}.apc-ask:hover{opacity:.9}.apc-paid{font-weight:700;color:var(--warm)}
</style>
