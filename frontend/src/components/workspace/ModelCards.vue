<template>
  <div class="mm-models">
    <div class="mm-conn-card mm-inuse"><Sparkles aria-hidden="true" /><div><b>{{ inUseLine(state.llm, cards) }}</b><p class="mm-conn-help">You can still pick another model for each chat in the chat box.</p></div></div>
    <p v-if="locked" class="mm-note" role="status"><Lock :size="14" /> {{ state.llm.locked_reason || 'This deployment sets its models in its configuration.' }} You can see what is connected, but not change it here.</p>
    <p v-if="error" class="mm-conn-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="mm-conn-ok" role="status">{{ notice }}</p>

    <template v-if="cards.logins.length">
      <h4 class="mm-conn-group">Signed in on this computer</h4>
      <div class="mm-conn-list">
        <article v-for="card in cards.logins" :key="card.id" class="mm-conn-card" :class="{ 'is-active': card.inUse }">
          <div class="mm-conn-card-top">
            <span class="mm-conn-icon"><BrandIcon v-if="brand(card.icon)" :brand="brand(card.icon)" :size="20" /><KeyRound v-else aria-hidden="true" /></span>
            <div class="mm-conn-body">
              <div class="mm-conn-title"><h3>{{ card.name }}</h3><span class="mm-badge" :class="modelStatus(card.status).tone">{{ modelStatus(card.status).label }}</span><span v-if="card.inUse" class="mm-badge accent">In use</span></div>
              <p class="mm-conn-meta">{{ card.help }}</p>
              <p v-if="card.models.length" class="mm-conn-meta">Models: {{ card.models.slice(0, 6).join(', ') }}{{ card.models.length > 6 ? ` and ${card.models.length - 6} more` : '' }}</p>
            </div>
            <Button v-if="!locked && !card.inUse" variant="outline" size="sm" :disabled="!!busy || card.status === 'needs_connection' && !card.models.length" @click="useLogin(card)"><LoaderCircle v-if="busy === card.id" class="mm-spin" />{{ busy === card.id ? 'Connecting…' : 'Use this' }}</Button>
          </div>
        </article>
      </div>
    </template>

    <h4 class="mm-conn-group">With an API key</h4>
    <div class="mm-conn-list">
      <article v-for="card in visibleApis" :key="card.id" class="mm-conn-card" :class="{ 'is-active': card.inUse }" :aria-labelledby="`${uid}-${card.provider}`">
        <div class="mm-conn-card-top">
          <span class="mm-conn-icon"><BrandIcon v-if="brand(card.icon)" :brand="brand(card.icon)" :size="20" /><Server v-else-if="card.keyOptional" aria-hidden="true" /><Cpu v-else aria-hidden="true" /></span>
          <div class="mm-conn-body">
            <div class="mm-conn-title"><h3 :id="`${uid}-${card.provider}`">{{ card.name }}</h3><span class="mm-badge" :class="modelStatus(card.status).tone">{{ modelStatus(card.status).label }}</span><span v-if="card.inUse" class="mm-badge accent">In use</span></div>
            <p class="mm-conn-meta">{{ card.help }}<template v-if="card.inUse && state.llm.model"> Model: {{ state.llm.model }}.</template></p>
          </div>
          <Button v-if="!locked && editingId !== card.id" variant="outline" size="sm" :aria-expanded="false" :aria-controls="`${uid}-${card.provider}-edit`" @click="startEdit(card)">{{ card.inUse ? 'Edit' : card.status === 'not_set_up' ? 'Set up' : 'Use this' }}</Button>
        </div>
        <form v-if="editingId === card.id" :id="`${uid}-${card.provider}-edit`" class="mm-form mm-model-form" novalidate @submit.prevent="save(card)">
          <div class="mm-field"><label :for="`${uid}-key`">API key<small v-if="card.keyOptional"> (optional)</small></label>
            <div class="mm-secret"><input :id="`${uid}-key`" v-model="form.api_key" class="mm-input" :type="showKey ? 'text' : 'password'" autocomplete="new-password" spellcheck="false" :placeholder="card.key_configured ? 'Saved. Leave blank to keep it' : card.keyOptional ? 'Only if your server needs one' : 'Paste your key'" :aria-describedby="`${uid}-key-help`" /><Button type="button" variant="outline" size="sm" :aria-pressed="showKey" :aria-label="showKey ? 'Hide key' : 'Show key'" @click="showKey = !showKey"><EyeOff v-if="showKey" /><Eye v-else /></Button><Button type="button" variant="outline" size="sm" :disabled="!!busy" @click="check(card, false)"><LoaderCircle v-if="busy === 'test'" class="mm-spin" />{{ busy === 'test' ? 'Checking…' : 'Test' }}</Button></div>
            <small :id="`${uid}-key-help`">Test only asks {{ card.name }} for its model list, which is free. Keys stay on this computer and are never shown again.</small>
          </div>
          <div aria-live="polite">
            <p v-if="result?.ok === true" class="mm-conn-ok">{{ result.message }}</p>
            <p v-else-if="result?.ok === false" class="mm-conn-error">{{ result.message }}</p>
            <div v-else-if="result?.status === 'needs_call'" class="mm-note mm-ask" role="group" aria-label="Run a check call?"><span>{{ result.message }} Run it?</span><span><Button type="button" size="sm" :disabled="!!busy || !form.model" @click="check(card, true)">Run one check call</Button><Button type="button" variant="ghost" size="sm" @click="result = null">Not now</Button></span><small v-if="!form.model">Enter a model name first.</small></div>
          </div>
          <label class="mm-field">Model<input v-model="form.model" class="mm-input" :list="`${uid}-models`" maxlength="200" autocomplete="off" spellcheck="false" :placeholder="card.model || 'Model name from your provider'" /><small>{{ result?.models?.length ? 'Pick one the check found, or type another.' : 'The name your provider uses, for example ' + (card.model || 'gpt-4o-mini') + '.' }}</small></label>
          <datalist :id="`${uid}-models`"><option v-for="m in result?.models || []" :key="m" :value="m" /></datalist>
          <details class="mm-advanced" :open="card.provider === 'custom' || undefined"><summary><ChevronRight aria-hidden="true" />Advanced</summary><div>
            <label class="mm-field">API address<input v-model="form.base_url" class="mm-input" type="url" inputmode="url" spellcheck="false" :placeholder="card.base_url || 'https://your-server.example/v1'" /><small>Leave as it is unless you use a proxy or your own server. A saved key is only sent to its own provider; type it again to use another address.</small></label>
          </div></details>
          <p v-if="formError" class="mm-conn-error" role="alert">{{ formError }}</p>
          <div class="mm-conn-actions"><span class="spacer"></span><Button type="button" variant="ghost" size="sm" @click="editingId = ''">Cancel</Button><Button type="submit" size="sm" :disabled="!!busy"><LoaderCircle v-if="busy === 'save'" class="mm-spin" />{{ busy === 'save' ? 'Saving…' : `Use ${card.name}` }}</Button></div>
        </form>
      </article>
    </div>
    <Button v-if="cards.apis.length > visibleApis.length || showAll" variant="ghost" size="sm" class="mm-more" :aria-expanded="showAll" @click="showAll = !showAll"><ChevronDown :class="{ 'mm-rot': showAll }" />{{ showAll ? 'Show fewer providers' : `Show all ${cards.apis.length} providers` }}</Button>

    <template v-if="!locked">
      <h4 class="mm-conn-group">On this computer</h4>
      <div class="mm-conn-card">
        <div class="mm-conn-card-top">
          <span class="mm-conn-icon"><HardDrive aria-hidden="true" /></span>
          <div class="mm-conn-body"><div class="mm-conn-title"><h3>Installed models</h3><span v-if="localModels" class="mm-badge" :class="localModels.models.length ? 'ok' : 'idle'">{{ localModels.models.length ? `${localModels.models.length} found` : 'None found' }}</span></div><p class="mm-conn-meta">Looks for Ollama and LM Studio on this computer. Nothing is downloaded or run.</p></div>
          <Button variant="outline" size="sm" :disabled="discovering" @click="discover"><LoaderCircle v-if="discovering" class="mm-spin" />{{ discovering ? 'Looking…' : localModels ? 'Look again' : 'Find models' }}</Button>
        </div>
        <ul v-if="localModels?.models.length" class="mm-local-list">
          <li v-for="m in localModels.models.slice(0, 20)" :key="`${m.base_url}:${m.id}`"><span><b>{{ m.id }}</b><small>{{ m.provider }}</small></span><Button variant="ghost" size="sm" :disabled="!!busy" @click="useLocal(m)">Use this</Button></li>
        </ul>
        <p v-if="localModels?.truncated" class="mm-conn-help">Showing the first models only.</p>
      </div>
      <details class="mm-advanced mm-pool"><summary><ChevronRight aria-hidden="true" />Advanced: spread simulated people across several providers</summary><div>
        <label class="mm-field">Agent model pool<input v-model="pool" class="mm-input" placeholder="Blank for the default, auto, or openai,claude,gemini" /><small>Used by simulations only; chat keeps the model above. Providers without a key are skipped. Use provider:model to pick a model.</small></label>
        <div class="mm-conn-actions" style="margin-top:0"><span class="spacer"></span><Button type="button" size="sm" variant="outline" :disabled="!!busy || pool === (state.llm.pool || '')" @click="savePool">Save pool</Button></div>
      </div></details>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, useId, watch } from 'vue'
import { ChevronDown, ChevronRight, Cpu, Eye, EyeOff, HardDrive, KeyRound, LoaderCircle, Lock, Server, Sparkles } from 'lucide-vue-next'
import { Button } from '../ui/button'
import BrandIcon from '../BrandIcon.vue'
import { api } from '../../workspace/api.js'
import { checkMatchesSaved, inUseLine, modelCards, modelStatus, providerAddress, visibleApiCards } from '../../workspace/connections.js'

const props = defineProps({ state: { type: Object, required: true }, theme: { type: String, default: 'light' }, initialProvider: { type: String, default: '' } })
const emit = defineEmits(['saved'])
const uid = useId()
const catalog = ref([]), tested = ref({}), showAll = ref(false), editingId = ref(''), busy = ref(''), error = ref(''), notice = ref('')
const form = ref({ api_key: '', model: '', base_url: '' }), showKey = ref(false), result = ref(null), formError = ref('')
const localModels = ref(null), discovering = ref(false), pool = ref(props.state.llm.pool || '')
const locked = computed(() => !!props.state.llm.locked)
const cards = computed(() => modelCards(props.state.llm, catalog.value, tested.value))
const visibleApis = computed(() => {
  const list = visibleApiCards(cards.value.apis, showAll.value)
  const editing = cards.value.apis.find(c => c.id === editingId.value)
  return editing && !list.includes(editing) ? [...list, editing] : list
})
function brand(id) { return ({ claude: 'anthropic', anthropic: 'anthropic', gemini: 'googlegemini', antigravity: 'googlegemini', ollama: 'ollama' })[id] || '' }

async function loadCatalog() { try { catalog.value = (await api('/api/workspace/models')).models || [] } catch { catalog.value = [] } }
// Bumped when the open editor changes (open, switch, cancel, save), so a late key check never lands in another editor.
let checkRun = 0
watch(editingId, () => { checkRun++ })
function startEdit(card) {
  editingId.value = card.id; showKey.value = false; result.value = null; formError.value = ''; notice.value = ''
  // Start from the address the server uses for this provider today, so Test and Save take the same route.
  form.value = { api_key: '', model: card.inUse ? props.state.llm.model : card.model || '', base_url: providerAddress(card, props.state.llm) }
}
function payload(card) {
  return { provider: card.provider, ...(form.value.api_key ? { api_key: form.value.api_key } : {}), ...(form.value.base_url.trim() ? { base_url: form.value.base_url.trim() } : {}), ...(form.value.model.trim() ? { model: form.value.model.trim() } : {}) }
}
async function check(card, allowCall) {
  busy.value = 'test'; formError.value = ''
  const run = checkRun, editor = editingId.value
  const body = { ...payload(card), ...(allowCall ? { allow_call: true } : {}) }
  try {
    const answer = await api('/api/workspace/settings/test', { method: 'POST', body })
    // Only a check of the saved setup changes the card's badge; a typed key or another address stays in the editor.
    if (['connected', 'key_rejected'].includes(answer.status) && checkMatchesSaved(body, card, props.state.llm)) tested.value = { ...tested.value, [card.provider]: { status: answer.status } }
    if (run !== checkRun || editingId.value !== editor) return
    result.value = answer
    if (answer.ok && !form.value.model && answer.models?.length) form.value.model = answer.models[0]
  } catch (e) { if (run === checkRun && editingId.value === editor) { formError.value = e.message; result.value = null } }
  finally { busy.value = '' }
}
async function save(card) {
  formError.value = ''
  if (!form.value.model.trim() && !card.model) { formError.value = 'Enter a model name.'; return }
  if (card.provider === 'custom' && !form.value.base_url.trim() && !card.base_url) { formError.value = 'Enter the address of your model server under Advanced.'; return }
  busy.value = 'save'
  try {
    const body = { ...payload(card) }
    delete body.allow_call
    const next = await api('/api/workspace/settings', { method: 'PUT', body: { llm: body } })
    form.value.api_key = ''; editingId.value = ''
    notice.value = `${card.name} is now the default for new chats.`
    emit('saved', next); window.dispatchEvent(new Event('mm-provider-changed'))
    await loadCatalog()
  } catch (e) { formError.value = e.message }
  finally { busy.value = '' }
}
async function useLogin(card) {
  busy.value = card.id; error.value = ''; notice.value = ''
  try {
    const model = card.models.includes('sonnet') ? 'sonnet' : card.models[0] || ''
    await api('/api/setup/provider', { method: 'POST', body: { kind: 'login', backend: card.backend, ...(model ? { model } : {}) } })
    const next = await api('/api/workspace/settings')
    notice.value = `Your ${card.name} is now the default for new chats.`
    emit('saved', next); window.dispatchEvent(new Event('mm-provider-changed'))
    await loadCatalog()
  } catch (e) { error.value = e.message }
  finally { busy.value = '' }
}
async function discover() {
  discovering.value = true; error.value = ''
  try { localModels.value = await api('/api/workspace/local-models?refresh=1') } catch (e) { error.value = e.message }
  finally { discovering.value = false }
}
async function useLocal(m) {
  busy.value = 'local'; error.value = ''; notice.value = ''
  try {
    const next = await api('/api/workspace/settings', { method: 'PUT', body: { llm: { provider: m.provider === 'ollama' ? 'ollama' : 'custom', base_url: m.base_url, model: m.id, api_key: '' } } })
    notice.value = `${m.id} is now the default for new chats.`
    emit('saved', next); window.dispatchEvent(new Event('mm-provider-changed'))
    await loadCatalog()
  } catch (e) { error.value = e.message }
  finally { busy.value = '' }
}
async function savePool() {
  busy.value = 'pool'; error.value = ''; notice.value = ''
  try { const next = await api('/api/workspace/settings', { method: 'PUT', body: { llm: { pool: pool.value } } }); notice.value = 'Agent model pool saved.'; emit('saved', next) }
  catch (e) { error.value = e.message }
  finally { busy.value = '' }
}
watch(() => props.state.llm.pool, value => { pool.value = value || '' })
loadCatalog().then(() => {
  const wanted = ({ anthropic: 'claude', compatible: 'custom' })[props.initialProvider] || props.initialProvider
  const card = wanted && cards.value.apis.find(c => c.provider === wanted)
  if (card && !locked.value) { showAll.value = !visibleApiCards(cards.value.apis, false).includes(card); startEdit(card) }
})
</script>

<style scoped>
.mm-models { display: grid; gap: 10px; }
.mm-models .mm-conn-group { margin: 14px 0 0; }
.mm-inuse { display: flex; gap: 12px; align-items: flex-start; background: var(--panel-2); }
.mm-inuse > svg { width: 18px; height: 18px; color: var(--accent); flex-shrink: 0; margin-top: 2px; }
.mm-inuse b { font-size: 13.5px; font-weight: 600; }
.mm-note { display: flex; gap: 8px; align-items: flex-start; margin: 0; }
.mm-model-form { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
.mm-ask { display: grid; gap: 8px; margin: 0; }
.mm-ask > span:last-of-type { display: flex; gap: 6px; flex-wrap: wrap; }
.mm-more { justify-self: start; }
.mm-rot { transform: rotate(180deg); }
.mm-local-list { list-style: none; margin: 12px 0 0; padding: 0; border-top: 1px solid var(--line); }
.mm-local-list li { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--line); }
.mm-local-list li:last-child { border-bottom: 0; }
.mm-local-list span { display: grid; min-width: 0; }
.mm-local-list b { font-size: 12.5px; font-weight: 600; overflow-wrap: anywhere; }
.mm-local-list small { font-size: 11.5px; color: var(--muted); }
.mm-pool { margin-top: 10px; }
.mm-spin { animation: mm-spin 1s linear infinite; }
@keyframes mm-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .mm-spin { animation: none; } }
@media (max-width: 520px) {
  .mm-conn-card-top { flex-wrap: wrap; }
  .mm-conn-card-top > button { margin-left: 48px; }
  .mm-secret { flex-wrap: wrap; }
  .mm-secret .mm-input { flex-basis: 100%; }
}
</style>
