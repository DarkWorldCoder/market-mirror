<template>
  <section ref="host" class="run-audience-card" aria-label="Saved audience visualization">
    <p v-if="loading" class="audience-card-loading" role="status"><LoaderCircle :size="17" />Opening the saved audience…</p>
    <p v-else-if="error" class="ws-error" role="alert">{{ error }}<button class="ws-btn" @click="load">Retry</button></p>
    <template v-else-if="loaded">
      <div class="audience-card-toolbar">
        <span>Audience explorer</span>
        <div>
          <div v-if="people.length" class="audience-views" role="group" aria-label="Audience view">
            <button type="button" :aria-pressed="view === 'map'" @click="view = 'map'"><MapIcon :size="14" aria-hidden="true" />World map</button>
            <button type="button" :aria-pressed="view === 'globe'" @click="view = 'globe'"><Globe2 :size="14" aria-hidden="true" />3D globe</button>
          </div>
          <InfoHint :theme="theme" label="Audience source">Saved simulation data from {{ detail?.title || name }}.</InfoHint>
          <button aria-label="Expand audience in chat" title="Expand audience" @click="expanded = true"><Maximize2 :size="16" /></button>
        </div>
      </div>
      <template v-if="people.length && visible && !expanded">
        <div v-if="view === 'map'">
          <WorldFlowMap :index="index" :story="story" :harvest="harvest" :theme="theme" :live="isRunning" :height="340" :selected="selectedId" @select="selectPerson" />
          <label class="audience-person-pick">Person<select v-model="selectedId" aria-label="Choose a simulated person"><option v-for="p in people" :key="p.agent_id" :value="String(p.agent_id)">{{ p.name || `Person ${p.agent_id}` }} · {{ p.segment || p.country || 'no segment' }}</option></select></label>
          <AudiencePersonCard v-if="selectedPerson" v-bind="cardProps" />
        </div>
        <div v-else ref="sceneHost"><PersonaScene :people="people" :activity="activity" :timeline="timeline" :responses="survey?.responses || []" :theme="theme" :status="detail?.status || ''" :checked-at="checkedAt" :selected-person-id="selectedId" :thoughts="harvest?.entries || []" :edges="edges" :names="names" @select="selectPerson" /></div>
      </template>
      <p v-else-if="!people.length" class="ws-note">No persona profiles were saved in this experiment. Choose another run to explore an audience.</p>
      <div v-else-if="!expanded" :style="{ minHeight: `${sceneHeight}px` }" class="ws-note">The audience resumes when this report is visible.</div>
      <details v-if="people.length" class="audience-country"><summary>People by country</summary><EChart :option="countryChart" :theme="theme" :height="250" label="Saved simulated persona profile counts by country" /></details>
    </template>
    <Dialog v-model:open="expanded">
      <DialogContent class="ws-overlay audience-expanded-dialog" :data-theme="theme">
        <DialogHeader class="audience-expanded-header">
          <DialogTitle>Audience explorer</DialogTitle>
          <DialogDescription>Choose a person to view their profile, what they did and what they thought.</DialogDescription>
        </DialogHeader>
        <div class="audience-expanded-body">
          <div class="audience-views" role="group" aria-label="Audience view">
            <button type="button" :aria-pressed="view === 'map'" @click="view = 'map'"><MapIcon :size="14" aria-hidden="true" />World map</button>
            <button type="button" :aria-pressed="view === 'globe'" @click="view = 'globe'"><Globe2 :size="14" aria-hidden="true" />3D globe</button>
          </div>
          <template v-if="view === 'map'">
            <WorldFlowMap big :index="index" :story="story" :harvest="harvest" :theme="theme" :live="isRunning" :height="480" :selected="selectedId" @select="selectPerson" />
            <label class="audience-person-pick">Person<select v-model="selectedId" aria-label="Choose a simulated person"><option v-for="p in people" :key="p.agent_id" :value="String(p.agent_id)">{{ p.name || `Person ${p.agent_id}` }} · {{ p.segment || p.country || 'no segment' }}</option></select></label>
            <AudiencePersonCard v-if="selectedPerson" v-bind="cardProps" />
          </template>
          <PersonaScene v-else :people="people" :activity="activity" :timeline="timeline" :responses="survey?.responses || []" :theme="theme" :status="detail?.status || ''" :checked-at="checkedAt" :selected-person-id="selectedId" :thoughts="harvest?.entries || []" :edges="edges" :names="names" @select="selectPerson" />
        </div>
      </DialogContent>
    </Dialog>
  </section>
</template>
<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog'
import InfoHint from './InfoHint.vue'
import { Globe2, LoaderCircle, Map as MapIcon, Maximize2 } from 'lucide-vue-next'
import EChart from './EChart.vue'
import AudiencePersonCard from './AudiencePersonCard.vue'
import { api } from '../../workspace/api'
import { peopleOption } from '../../workspace/charts'
import { SEGMENT_COLORS } from '../../workspace/geoPlace'
import { feedEdges } from '../../workspace/runActivity'
const PersonaScene = defineAsyncComponent(() => import('./PersonaScene.vue'))
const WorldFlowMap = defineAsyncComponent(() => import('./WorldFlowMap.vue'))
const props = defineProps({ name: { type: String, required: true }, theme: { type: String, default: 'light' } })
const expanded = ref(false), view = ref('')
const host = ref(null), sceneHost = ref(null), sceneHeight = ref(600), visible = ref(false), loading = ref(true), loaded = ref(false), error = ref(''), detail = ref(null), config = ref(null), survey = ref(null), activity = ref([]), timeline = ref([]), harvest = ref(null), story = ref(null), selectedId = ref(''), checkedAt = ref('')
let observer, refreshTimer, request = 0, pendingLoads = 0
const index = computed(() => config.value?.persona_index || [])
const people = computed(() => index.value.filter(person => (person.kind || 'persona') === 'persona'))
const names = computed(() => Object.fromEntries(index.value.map(person => [String(person.agent_id), person.name])))
const segments = computed(() => [...new Set(people.value.map(p => p.segment || 'Unspecified segment'))])
const selectedPerson = computed(() => people.value.find(person => String(person.agent_id) === selectedId.value))
const edges = computed(() => feedEdges(story.value))
const isRunning = computed(() => /^(running|preparing|processing|in_progress)$/i.test(detail.value?.status || ''))
const countryChart = computed(() => { props.theme; return peopleOption(people.value) })
const cardProps = computed(() => {
  const id = selectedId.value, person = selectedPerson.value
  const answer = (survey.value?.responses || []).find(r => String(r.agent_id) === id)?.answer || null
  return {
    person, answer, names: names.value,
    askTo: person && (person.kind || 'persona') === 'persona' ? { path: `/workspace/runs/${props.name}`, query: { ask: String(person.agent_id) } } : null,
    color: SEGMENT_COLORS[Math.max(0, segments.value.indexOf(person?.segment || 'Unspecified segment')) % SEGMENT_COLORS.length],
    stats: activity.value.find(r => String(r.agent_id) === id) || null,
    // the card shows the survey answer itself, so the survey objection is not repeated as a thought
    thoughts: (harvest.value?.entries || []).filter(t => String(t.agent_id) === id && t.text && !(answer && t.source === 'survey')),
    edges: edges.value.filter(e => String(e.from) === id || String(e.to) === id)
  }
})
function selectPerson(id) { if (people.value.some(person => String(person.agent_id) === String(id))) selectedId.value = String(id) }
async function load() {
 const ticket = ++request; pendingLoads++; if (!loaded.value) loading.value = true; error.value = ''
 try {
  const enc = encodeURIComponent(props.name)
  const run = await api(`/api/runs/${enc}`), available = new Set(run.files || []), files = {}
  await Promise.all(['config.json','survey.json','agent_stats.json','timeline.json','feed_story.json'].filter(file => available.has(file)).map(async file => { files[file] = await api(`/api/runs/${enc}/files/${encodeURIComponent(file)}`) }))
  // what people thought, said and posted, harvested by the backend from the run's saved files (no model call)
  const thoughts = await api(`/api/runs/${enc}/thoughts`).catch(() => null)
  if (ticket !== request) return
  detail.value = run; config.value = files['config.json'] || null; survey.value = files['survey.json'] || null
  const stats = files['agent_stats.json']; activity.value = Array.isArray(stats) ? stats : stats?.agents || []
  timeline.value = Array.isArray(files['timeline.json']) ? files['timeline.json'] : []
  story.value = files['feed_story.json'] || null
  harvest.value = thoughts && Array.isArray(thoughts.entries) ? thoughts : { entries: [] }
  if (!view.value) view.value = edges.value.length ? 'map' : 'globe'
  if (!people.value.some(person => String(person.agent_id) === selectedId.value)) selectedId.value = people.value[0] ? String(people.value[0].agent_id) : ''
  checkedAt.value = new Date().toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}); loaded.value = true
 } catch (err) { if (ticket === request) error.value = err.message }
 finally { pendingLoads--; if (ticket === request) loading.value = false }
}
watch(() => props.name, () => { request++; loaded.value = false; view.value = ''; if (visible.value) load() })
onMounted(() => {
 if (typeof IntersectionObserver === 'undefined') { visible.value = true; load(); return }
 observer = new IntersectionObserver(entries => { if (!entries[0].isIntersecting && sceneHost.value) sceneHeight.value = sceneHost.value.offsetHeight; visible.value = entries[0].isIntersecting; if (visible.value && !loaded.value && !error.value && !pendingLoads) load() }, { rootMargin: '250px' }); observer.observe(host.value)
 refreshTimer = setInterval(() => { if (visible.value && loaded.value && !pendingLoads && isRunning.value) load() }, 8000)
})
onBeforeUnmount(() => { request++; observer?.disconnect(); clearInterval(refreshTimer) })
</script>
<style scoped>
.audience-card-toolbar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;font-size:13px;font-weight:550;margin-bottom:16px}.audience-card-toolbar>div{display:flex;align-items:center;flex-wrap:wrap;gap:6px}.audience-card-toolbar>div>button{display:grid;place-items:center;width:30px;height:30px;border:1px solid var(--line);border-radius:8px;background:var(--panel);cursor:pointer}
.audience-views{display:inline-flex;gap:2px;padding:3px;border:1px solid var(--line);border-radius:9px;background:var(--panel-2)}.audience-views button{display:inline-flex;align-items:center;gap:5px;border:0;background:none;border-radius:6px;padding:4px 10px;font-size:12px;font-weight:500;color:var(--muted);cursor:pointer}.audience-views button[aria-pressed='true']{background:var(--panel);color:var(--text);box-shadow:0 1px 2px rgb(0 0 0 / 10%)}.audience-expanded-body>.audience-views{margin-bottom:12px}
.audience-person-pick{display:flex;align-items:center;gap:8px;margin-top:14px;font-size:12px;color:var(--muted)}.audience-person-pick select{flex:1;min-width:0;max-width:420px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);padding:6px 8px;font:inherit;font-size:12.5px}
:global(.audience-expanded-dialog){width:min(1180px,calc(100vw - 24px))!important;max-width:1180px!important;height:90dvh;max-height:90dvh;display:flex!important;flex-direction:column;padding:0!important;gap:0!important;overflow:hidden;background:var(--panel)!important;color:var(--text)!important;border-radius:20px!important}.audience-expanded-header{padding:20px 26px;border-bottom:1px solid var(--line);flex-shrink:0}.audience-expanded-body{overflow:auto;min-height:0;padding:22px 26px}.audience-expanded-body :deep(.persona-viewport){height:min(46dvh,440px)}.run-audience-card{border:1px solid var(--line);border-radius:17px;padding:20px;background:var(--panel);margin-top:17px;min-width:0}.audience-card-loading{display:flex;align-items:center;gap:9px;min-height:120px;font-size:12px;color:var(--muted)}.audience-card-loading svg{animation:audience-card-spin 1s linear infinite}.audience-country{margin-top:20px;padding-top:15px;border-top:1px solid var(--line)}.audience-country>summary{font-size:12px;cursor:pointer}.run-audience-card :deep(.persona-viewport){height:330px}.ws-note{font-size:11px;line-height:1.7;color:var(--muted)}@keyframes audience-card-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.audience-card-loading svg{animation:none}}@media(max-width:600px){.run-audience-card{padding:15px}.run-audience-card :deep(.persona-viewport){height:280px}.audience-views button{padding:4px 8px}}
</style>
