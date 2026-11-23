<template>
  <section ref="host" class="run-audience-card" aria-label="Saved audience visualization">
    <p v-if="loading" class="audience-card-loading" role="status"><LoaderCircle :size="17" />Opening the saved audience…</p>
    <p v-else-if="error" class="ws-error" role="alert">{{ error }}<button class="ws-btn" @click="load">Retry</button></p>
    <template v-else-if="loaded">
      <div class="audience-card-toolbar"><span>Audience explorer</span><div><InfoHint :theme="theme" label="Audience source">Saved simulation data from {{ detail?.title || name }}.</InfoHint><button aria-label="Expand audience in chat" title="Expand audience" @click="expanded = true"><Maximize2 :size="16" /></button></div></div>
      <div v-if="people.length && visible && !expanded" ref="sceneHost"><PersonaScene :people="people" :activity="activity" :timeline="timeline" :responses="survey?.responses || []" :theme="theme" :status="detail?.status || ''" :checked-at="checkedAt" :selected-person-id="selectedId" @select="selectPerson" /></div>
      <p v-else-if="!people.length" class="ws-note">No persona profiles were saved in this experiment. Choose another run to explore an audience.</p>
      <div v-else-if="!expanded" :style="{ minHeight: `${sceneHeight}px` }" class="ws-note">The 3D audience resumes when this report is visible.</div>
      <details v-if="people.length" class="audience-country"><summary>People by country</summary><EChart :option="countryChart" :theme="theme" :height="250" label="Saved simulated persona profile counts by country" /></details>
      <section v-if="selectedPerson && personThoughts.length" class="audience-thoughts"><h4>Recorded thoughts</h4><WorkspacePager v-model:page="thoughtPage" :total="personThoughts.length" label="recorded thoughts" :size="10" /><article v-for="(thought,index) in pagedThoughts" :key="index"><small>{{ thought.source }}</small><p>{{ thought.text }}</p></article></section>
    </template>
    <Dialog v-model:open="expanded"><DialogContent class="ws-overlay audience-expanded-dialog" :data-theme="theme"><DialogHeader class="audience-expanded-header"><DialogTitle>Audience explorer</DialogTitle><DialogDescription>Choose a person to view their profile and recorded responses.</DialogDescription></DialogHeader><div class="audience-expanded-body"><PersonaScene :people="people" :activity="activity" :timeline="timeline" :responses="survey?.responses || []" :theme="theme" :status="detail?.status || ''" :checked-at="checkedAt" :selected-person-id="selectedId" @select="selectPerson" /><section v-if="selectedPerson && personThoughts.length" class="audience-thoughts"><h4>Recorded thoughts</h4><WorkspacePager v-model:page="thoughtPage" :total="personThoughts.length" label="recorded thoughts" :size="10" /><article v-for="(thought,index) in pagedThoughts" :key="index"><small>{{ thought.source }}</small><p>{{ thought.text }}</p></article></section></div></DialogContent></Dialog>
  </section>
</template>
<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog'
import InfoHint from './InfoHint.vue'
import { LoaderCircle, Maximize2 } from 'lucide-vue-next'
import EChart from './EChart.vue'
import WorkspacePager from './WorkspacePager.vue'
import { api } from '../../workspace/api'
import { peopleOption } from '../../workspace/charts'
const PersonaScene = defineAsyncComponent(() => import('./PersonaScene.vue'))
const props = defineProps({ name: { type: String, required: true }, theme: { type: String, default: 'light' } })
const expanded = ref(false)
const host = ref(null), sceneHost = ref(null), sceneHeight = ref(600), visible = ref(false), loading = ref(true), loaded = ref(false), error = ref(''), detail = ref(null), config = ref(null), survey = ref(null), activity = ref([]), timeline = ref([]), thoughts = ref([]), selectedId = ref(''), thoughtPage = ref(0), checkedAt = ref('')
let observer, refreshTimer, request = 0, pendingLoads = 0
const people = computed(() => (config.value?.persona_index || []).filter(person => (person.kind || 'persona') === 'persona'))
const selectedPerson = computed(() => people.value.find(person => String(person.agent_id) === selectedId.value))
const countryChart = computed(() => { props.theme; return peopleOption(people.value) })
const personThoughts = computed(() => {
 const saved = thoughts.value.filter(item => String(item.agent_id) === selectedId.value).map(item => ({ source: item.source || 'Recorded thought', text: item.text || item.thought })).filter(item => item.text)
 const answer = survey.value?.responses?.find(response => String(response.agent_id) === selectedId.value)?.answer
 return saved.filter(item => item.text !== answer?.quote && item.text !== answer?.main_objection)
})
const pagedThoughts = computed(() => personThoughts.value.slice(thoughtPage.value * 10, (thoughtPage.value + 1) * 10))
function selectPerson(id) { selectedId.value = id; thoughtPage.value = 0 }
async function load() {
 const ticket = ++request; pendingLoads++; if (!loaded.value) loading.value = true; error.value = ''
 try {
  const run = await api(`/api/runs/${encodeURIComponent(props.name)}`), available = new Set(run.files || []), files = {}
  await Promise.all(['config.json','survey.json','agent_stats.json','timeline.json','thought_stream.json'].filter(file => available.has(file)).map(async file => { files[file] = await api(`/api/runs/${encodeURIComponent(props.name)}/files/${encodeURIComponent(file)}`) }))
  if (ticket !== request) return
  detail.value = run; config.value = files['config.json'] || null; survey.value = files['survey.json'] || null
  const stats = files['agent_stats.json']; activity.value = Array.isArray(stats) ? stats : stats?.agents || []
  timeline.value = Array.isArray(files['timeline.json']) ? files['timeline.json'] : []
  const stream = files['thought_stream.json']; thoughts.value = Array.isArray(stream) ? stream : stream?.thoughts || stream?.items || []
  if (!people.value.some(person => String(person.agent_id) === selectedId.value)) selectedId.value = people.value[0] ? String(people.value[0].agent_id) : ''
  checkedAt.value = new Date().toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}); loaded.value = true
 } catch (err) { if (ticket === request) error.value = err.message }
 finally { pendingLoads--; if (ticket === request) loading.value = false }
}
watch(() => props.name, () => { request++; loaded.value = false; if (visible.value) load() })
onMounted(() => {
 if (typeof IntersectionObserver === 'undefined') { visible.value = true; load(); return }
 observer = new IntersectionObserver(entries => { if (!entries[0].isIntersecting && sceneHost.value) sceneHeight.value = sceneHost.value.offsetHeight; visible.value = entries[0].isIntersecting; if (visible.value && !loaded.value && !error.value && !pendingLoads) load() }, { rootMargin: '250px' }); observer.observe(host.value)
 refreshTimer = setInterval(() => { if (visible.value && loaded.value && !pendingLoads && /^(running|preparing|processing|in_progress)$/i.test(detail.value?.status || '')) load() }, 8000)
})
onBeforeUnmount(() => { request++; observer?.disconnect(); clearInterval(refreshTimer) })
</script>
<style scoped>
.audience-card-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:13px;font-weight:550;margin-bottom:16px}.audience-card-toolbar>div{display:flex;align-items:center;gap:6px}.audience-card-toolbar button{display:grid;place-items:center;width:30px;height:30px;border:1px solid var(--line);border-radius:8px;background:var(--panel);cursor:pointer}:global(.audience-expanded-dialog){width:min(1120px,calc(100vw - 24px))!important;max-width:1120px!important;height:90dvh;max-height:90dvh;display:flex!important;flex-direction:column;padding:0!important;gap:0!important;overflow:hidden;background:var(--panel)!important;color:var(--text)!important;border-radius:20px!important}.audience-expanded-header{padding:20px 26px;border-bottom:1px solid var(--line);flex-shrink:0}.audience-expanded-body{overflow:auto;min-height:0;padding:22px 26px}.audience-expanded-body :deep(.persona-viewport){height:min(46dvh,440px)}.run-audience-card{border:1px solid var(--line);border-radius:17px;padding:20px;background:var(--panel);margin-top:17px;min-width:0}.audience-card-source{font-size:10px;line-height:1.7;color:var(--muted);margin-bottom:17px}.audience-card-loading{display:flex;align-items:center;gap:9px;min-height:120px;font-size:12px;color:var(--muted)}.audience-card-loading svg{animation:audience-card-spin 1s linear infinite}.audience-country{margin-top:20px;padding-top:15px;border-top:1px solid var(--line)}.audience-country>summary{font-size:12px;cursor:pointer}.audience-thoughts{margin-top:20px;padding-top:18px;border-top:1px solid var(--line)}.audience-thoughts h4{font-size:13px;font-weight:550;margin:0 0 6px}.audience-thoughts article{padding:12px 0;border-bottom:1px solid var(--line)}.audience-thoughts article small{font-size:10px;color:var(--muted)}.audience-thoughts article p{font-size:12px;line-height:1.8;margin-top:5px;white-space:pre-wrap}.run-audience-card :deep(.persona-viewport){height:330px}.ws-note{font-size:11px;line-height:1.7;color:var(--muted)}@keyframes audience-card-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.audience-card-loading svg{animation:none}}@media(max-width:600px){.run-audience-card{padding:15px}.run-audience-card :deep(.persona-viewport){height:280px}}
</style>
