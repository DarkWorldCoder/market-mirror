<script setup>
import { computed, ref, watch } from 'vue'
import { Brain, SlidersHorizontal, LoaderCircle, Check, ChevronRight, Cpu, Wallet, Plug } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog'
import { Button } from '../ui/button'
import InfoHint from './InfoHint.vue'
import './modal-controls.css'
import { api } from '../../workspace/api'

const props = defineProps({ open: Boolean, theme: { type: String, default: 'light' }, initialTab: { type: String, default: 'models' }, initialProvider: { type: String, default: '' } })
const emit = defineEmits(['update:open', 'saved', 'connectors', 'models'])
const tab = ref('models')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const state = ref(null)
const llm = ref({ provider: 'openai', model: '', base_url: '', api_key: '', pool: '' })
const cloudAccount = ref(null)
const modelSource = ref('byok')
const hostedRemaining = computed(() => cloudAccount.value?.hosted_model ? Math.max(0, Number(cloudAccount.value.hosted_model.limit_usd) - Number(cloudAccount.value.hosted_model.used_or_reserved_usd || 0)) : 0)
async function loadCloudAccount(){cloudAccount.value=null;modelSource.value='byok';try{const response=await fetch('/auth/session',{credentials:'same-origin',headers:{Accept:'application/json'}});if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))return;const value=await response.json();if(value?.account&&typeof value.account.id==='string'&&value.account.id&&typeof value.account.email==='string'&&value.account.email&&typeof value.csrf==='string'&&value.csrf){const hosted=value.hosted_model;if(hosted&&!(typeof hosted.id==='string'&&hosted.id&&typeof hosted.label==='string'&&typeof hosted.limit_usd==='number'&&Number.isFinite(hosted.limit_usd)&&hosted.limit_usd>=0&&hosted.estimate===true))value.hosted_model=null;cloudAccount.value=value;modelSource.value=value.hosted_model&&state.value?.llm.model===value.hosted_model.id&&state.value?.llm.base_url?.includes('/hosted/v1')?'hosted':'byok'}}catch{}}
function chooseSource(value){modelSource.value=value;if(value==='byok'&&state.value?.llm.base_url?.includes('/hosted/v1'))llm.value={provider:'openai',model:'',base_url:'https://api.openai.com/v1',api_key:'',pool:''}}
async function useHosted(){saving.value=true;error.value='';saved.value=false;try{const response=await fetch('/auth/use-hosted',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':cloudAccount.value.csrf,'X-MM-Workspace':cloudAccount.value.workspace?.id||''},body:'{}'});const value=await response.json();if(!response.ok||value.success!==true)throw new Error(value.error||'Could not select the MarketMirror model.');hydrate(await api('/api/workspace/settings'));await loadCloudAccount();saved.value=true;emit('saved',state.value)}catch(err){error.value=err.message}finally{saving.value=false}}
const localModels = ref(null)
const discovering = ref(false)
async function discoverLocalModels(){discovering.value=true;error.value='';try{localModels.value=await api('/api/workspace/local-models?refresh=1')}catch(err){error.value=err.message}finally{discovering.value=false}}
function chooseLocalModel(event){const selected=localModels.value?.models.find((item,index)=>String(index)===event.target.value);if(selected)llm.value={...llm.value,provider:selected.provider==='ollama'?'ollama':'custom',base_url:selected.base_url,model:selected.id,api_key:''}}
const spending = ref({ process_limit_usd: 0, input_price_usd_per_mtok: '', output_price_usd_per_mtok: '' })
const tabs = [{ id: 'models', label: 'Models', icon: Cpu }, { id: 'spending', label: 'Spending', icon: Wallet }, { id: 'memory', label: 'Memory', icon: Brain }, { id: 'jev', label: 'Decision engine', icon: SlidersHorizontal }, { id: 'connections', label: 'Connections', icon: Plug }]
function changeProvider() {
  const selected = state.value?.llm?.providers.find(item => item.id === llm.value.provider)
  if (selected) llm.value = { ...llm.value, model: selected.model, base_url: selected.base_url, api_key: '' }
}
const selectedModelProvider = computed(() => state.value?.llm?.providers.find(item => item.id === llm.value.provider))
const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(value || 0)
const memory = ref({ backend: 'local', embeddings: false, extract_activity: false, cognee_url: '', zep_api_key: '' })
const jev = ref({ route: 'typesafe', model: '', parallel: 4, timeout: 60, retries: 3, labels: 'auto', ssr_engine: 'embeddings', api_key: '' })
const provider = computed(() => state.value?.memory?.providers?.find(item => item.id === memory.value.backend))
function hydrate(value) {
  state.value = value
  llm.value = { ...llm.value, ...value.llm, api_key: '' }
  spending.value = { process_limit_usd: value.spending?.process_limit_usd || 0, input_price_usd_per_mtok: value.spending?.input_price_usd_per_mtok ?? '', output_price_usd_per_mtok: value.spending?.output_price_usd_per_mtok ?? '' }
  memory.value = { ...memory.value, ...value.memory, zep_api_key: '' }
  jev.value = { ...jev.value, ...value.jev, api_key: '' }
}
async function load() {
  loading.value = true; error.value = ''; saved.value = false
  try { hydrate(await api('/api/workspace/settings')); await loadCloudAccount(); const desired=({anthropic:'claude',compatible:'custom'})[props.initialProvider]||props.initialProvider; if(desired && state.value.llm.providers.some(item=>item.id===desired)){modelSource.value='byok';llm.value.provider=desired;changeProvider()} } catch (err) { error.value = err.message }
  finally { loading.value = false }
}
watch(() => props.open, value => { if (value) { tab.value=tabs.some(item=>item.id===props.initialTab)?props.initialTab:'models'; load() } }, { immediate: true })
async function save() {
  if(tab.value==='models'&&modelSource.value==='hosted'&&cloudAccount.value?.hosted_model){await useHosted();return}
  saving.value = true; error.value = ''; saved.value = false
  try {
    const bodies = {
      memory: { backend: memory.value.backend, embeddings: memory.value.embeddings, extract_activity: memory.value.extract_activity, ...(memory.value.backend === 'cognee' ? { cognee_url: memory.value.cognee_url } : {}), zep_api_key: memory.value.zep_api_key },
      jev: { route: jev.value.route, model: jev.value.model, parallel: Number(jev.value.parallel), timeout: Number(jev.value.timeout), retries: Number(jev.value.retries), labels: jev.value.labels, ssr_engine: jev.value.ssr_engine, api_key: jev.value.api_key },
      models: { provider: llm.value.provider, model: llm.value.model, base_url: llm.value.base_url, api_key: llm.value.api_key, ...(llm.value.pool !== state.value.llm.pool ? { pool: llm.value.pool } : {}) },
      spending: { process_limit_usd: Number(spending.value.process_limit_usd), input_price_usd_per_mtok: spending.value.input_price_usd_per_mtok === '' ? null : Number(spending.value.input_price_usd_per_mtok), output_price_usd_per_mtok: spending.value.output_price_usd_per_mtok === '' ? null : Number(spending.value.output_price_usd_per_mtok) },
    }
    const body = { [tab.value === 'models' ? 'llm' : tab.value]: bodies[tab.value] }
    hydrate(await api('/api/workspace/settings', { method: 'PUT', body }))
    saved.value = true; emit('saved', state.value)
  } catch (err) { error.value = err.message }
  finally { saving.value = false }
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="ws-overlay workspace-settings" :data-theme="theme">
      <DialogHeader class="settings-header">
        <DialogTitle>Settings</DialogTitle>
        <DialogDescription>Models, spending and memory.</DialogDescription>
      </DialogHeader>
      <div class="settings-body">
      <nav class="settings-tabs workspace-modal-tabs" aria-label="Settings sections">
        <button v-for="item in tabs" :key="item.id" type="button" :class="{ active: tab === item.id }" :aria-pressed="tab === item.id" @click="tab = item.id; saved = false; error = ''"><component :is="item.icon" :size="16" />{{ item.label }}</button>
      </nav>
      <div class="settings-main">
      <div v-if="loading" class="settings-loading" role="status"><LoaderCircle :size="20" class="settings-spin" />Loading your configuration…</div>
      <form v-else-if="state" class="settings-form" @submit.prevent="save">
        <div v-if="tab === 'connections'" class="settings-fields">
          <div class="settings-intro"><h3>Data & connections</h3><p>Connect analytics, ads and models.</p></div>
          <div class="settings-connection-row"><div><strong>Analytics & advertising</strong><p>Review Google Analytics, ad platforms, imports and their actual connection status.</p></div><Button type="button" variant="outline" @click="emit('connectors'); emit('update:open', false)">Manage connections<ChevronRight :size="14" /></Button></div>
          <div class="settings-connection-row"><div><strong>Local & connected chat models</strong><p>Choose an available model or open the model setup flow.</p></div><Button type="button" variant="outline" @click="emit('models'); emit('update:open', false)">View models<ChevronRight :size="14" /></Button></div>
          <div class="settings-help"><span>Manage access and imports in Connections.</span><InfoHint :theme="theme" label="Connection permissions">Connection status comes from this workspace’s configured services. Opening this panel does not authorize a new account or import data.</InfoHint></div>
        </div>
        <div v-else-if="tab === 'models'" class="settings-fields">
          <div class="settings-intro"><h3>Default model & API</h3><p>Choose the default model for new operations.</p></div>
          <div v-if="cloudAccount" class="settings-hosted-source"><div class="settings-account-line"><span>{{ cloudAccount.account.email }}</span><span class="settings-account-links"><a href="/team">Team</a><a href="/account">Account</a></span></div><div class="settings-source-options"><label v-if="cloudAccount.hosted_model"><input type="radio" name="model-source" :checked="modelSource === 'hosted'" @change="chooseSource('hosted')" /><span>MarketMirror model</span></label><label><input type="radio" name="model-source" :checked="modelSource === 'byok'" @change="chooseSource('byok')" /><span>Your API key / model</span></label></div><div v-if="modelSource === 'hosted' && cloudAccount.hosted_model" class="settings-help"><span>{{ cloudAccount.hosted_model.label }} · {{ money(hostedRemaining) }} estimated allowance left</span><InfoHint :theme="theme" label="MarketMirror model allowance">{{ money(cloudAccount.hosted_model.used_or_reserved_usd || 0) }} used or reserved of {{ money(cloudAccount.hosted_model.limit_usd) }}. This is an estimated usage allowance. Reservations may include pending or failed calls; it is not a billing balance or invoice.</InfoHint></div><p v-else-if="!cloudAccount.hosted_model" class="settings-note">Choose your own API provider or model endpoint.</p></div>
          <div v-if="modelSource === 'byok'" class="settings-fields">
          <div v-if="state.llm.gateway" class="settings-help"><span>Current gateway: {{ state.llm.gateway }}</span><InfoHint :theme="theme" label="Changing the default gateway">Saving an API provider replaces the current default. Connected local models remain in the chat model selector.</InfoHint></div>
          <label>Provider<select v-model="llm.provider" @change="changeProvider"><option v-for="item in state.llm.providers" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
          <div class="settings-local-models"><div><span>Models on this server</span><Button type="button" variant="outline" :disabled="discovering" @click="discoverLocalModels">{{ discovering ? 'Discovering…' : 'Discover local models' }}</Button></div><select v-if="localModels?.models.length" aria-label="Use a discovered local model" @change="chooseLocalModel"><option value="">Choose an installed model…</option><option v-for="(model,index) in localModels.models" :key="`${model.base_url}:${model.id}`" :value="String(index)">{{ model.id }} · {{ model.provider }}</option></select><p v-else-if="localModels" class="settings-note">No models discovered on configured local servers.</p><p v-if="localModels?.truncated" class="settings-note">Showing the first 300 installed models.</p><InfoHint :theme="theme" label="About local model discovery">Discovery reads model catalogs from loopback model servers inside this MarketMirror instance. Hosted workers cannot see models on your personal computer. No model is downloaded or run.</InfoHint></div>
          <label>Model identifier<input v-model="llm.model" required maxlength="200" placeholder="Model available in your account" /></label>
          <label>API base URL<input v-model="llm.base_url" type="url" required placeholder="https://api.example.com/v1" /></label>
          <label>API key<input v-model="llm.api_key" type="password" autocomplete="new-password" :placeholder="selectedModelProvider?.key_configured ? 'Key saved · leave blank to keep it' : ['ollama','custom'].includes(llm.provider) ? 'Optional when your server needs no token' : 'Enter the selected provider’s API key'" /></label>
          <div class="settings-help"><span>Saved on this instance.</span><InfoHint :theme="theme" label="API key storage">Keys stay on this MarketMirror instance. Saving makes no provider request. Provider keys are shared with other features using the same account.</InfoHint></div>
          <label>Agent model pool<input v-model="llm.pool" placeholder="Blank for default, auto, or openai,claude,gemini" /></label>
          <div class="settings-help"><span>Optional: use several providers for agent runs.</span><InfoHint :theme="theme" label="Model pool behavior">Pool-aware engine stages distribute agents across configured providers. Use provider:model to choose a model, or a JSON list of provider, model and base_url. Missing provider keys are skipped. The chat default stays the model above.</InfoHint></div>
          </div>
        </div>
        <div v-else-if="tab === 'spending'" class="settings-fields">
          <div class="settings-intro"><h3>Estimated model spending</h3><p>Set a limit for estimated model costs.</p></div>
          <div class="settings-spend-summary"><div><small>This process</small><strong>{{ money(state.spending.process_spent_usd) }}</strong><span>{{ state.spending.process_calls }} recorded calls</span></div><div><small>Current run cap</small><strong>{{ state.spending.run_cap ? money(state.spending.run_cap.spent_usd) + ' / ' + money(state.spending.run_cap.limit_usd) : 'No run cap armed' }}</strong><span>{{ state.spending.run_cap?.label || 'Set per-run budgets in the test workflow' }}</span></div></div>
          <label>Process spending limit (USD)<input v-model="spending.process_limit_usd" type="number" min="0" max="1000000" step="any" required /></label>
          <div class="settings-help"><span>0 disables the process limit.</span><InfoHint :theme="theme" label="Process spending limits">Zero disables this process limit. Lowering the limit below recorded spend stops the next covered call. Saving does not reset usage or change an active run cap.</InfoHint></div>
          <div class="settings-help"><span>Estimated cost, per process.</span><InfoHint :theme="theme" label="Spending enforcement details">{{ state.spending.enforcement }}</InfoHint></div>
          <div class="settings-intro"><h3>Cost estimate prices</h3><p>USD per million tokens. Blank uses the model price table.</p></div>
          <div class="settings-grid"><label>Input tokens<input v-model="spending.input_price_usd_per_mtok" type="number" min="0" max="1000000" step="any" placeholder="Model price table" /></label><label>Output tokens<input v-model="spending.output_price_usd_per_mtok" type="number" min="0" max="1000000" step="any" placeholder="Model price table" /></label></div>
          <div class="settings-help"><span>Costs are estimates.</span><InfoHint :theme="theme" label="How cost estimates work">Estimates depend on reported token usage and may differ from your invoice. These controls do not set a provider account billing limit.</InfoHint></div>
        </div>
        <div v-else-if="tab === 'memory'" class="settings-fields">
          <div class="settings-intro"><h3>Give personas useful context</h3><p>Choose how personas retain simulation context.</p></div>
          <label>Memory provider<select v-model="memory.backend"><option v-for="item in state.memory.providers.filter(item => item.supported)" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
          <div class="settings-help"><span>{{ provider?.label }}</span><InfoHint :theme="theme" label="Memory provider details">{{ provider?.description }}</InfoHint></div>
          <label v-if="memory.backend === 'cognee'">Cognee service URL<input v-model="memory.cognee_url" type="url" placeholder="http://localhost:8000" /></label>
          <label v-if="memory.backend === 'zep'">Zep API key<input v-model="memory.zep_api_key" type="password" autocomplete="new-password" :placeholder="state.memory.zep_key_configured ? 'Key saved · leave blank to keep it' : 'Enter your Zep API key'" /></label>
          <label class="settings-switch"><span><strong>Semantic retrieval</strong><small>Use embeddings to retrieve relevant persona memories.</small></span><input v-model="memory.embeddings" type="checkbox" /></label>
          <label class="settings-switch"><span><strong>Extract activity</strong><small>Extract memory from simulation activity during new operations.</small></span><input v-model="memory.extract_activity" type="checkbox" /></label>
        </div>
        <div v-else class="settings-fields">
          <div class="settings-intro"><h3>Jev decision model</h3><p>Set up the decision model for evaluations.</p></div>
          <p class="settings-status"><span :class="{ ready: state.jev.configured }"></span>{{ state.jev.configured ? 'Provider key configured' : 'Provider key needed' }}<small>{{ state.jev.reason }}</small></p>
          <div class="settings-grid"><label>Provider route<select v-model="jev.route"><option value="typesafe">Typesafe direct</option><option value="openrouter">OpenRouter</option></select></label><label>Model<input v-model="jev.model" placeholder="Use engine default" /></label></div>
          <label>Provider API key<input v-model="jev.api_key" type="password" autocomplete="new-password" :placeholder="state.jev.key_configured ? 'Key saved · leave blank to keep it' : 'Enter a key for the selected route'" /></label>
          <div v-if="jev.route === 'openrouter'" class="settings-help"><span>Shared OpenRouter account.</span><InfoHint :theme="theme" label="OpenRouter key sharing">The OpenRouter key is shared with other OpenRouter features in this workspace.</InfoHint></div>
          <div class="settings-grid settings-grid-three"><label>Parallel requests<input v-model="jev.parallel" type="number" min="1" max="32" required /></label><label>Timeout (seconds)<input v-model="jev.timeout" type="number" min="5" max="600" required /></label><label>Retries<input v-model="jev.retries" type="number" min="0" max="8" required /></label></div>
          <div class="settings-grid"><label>Persona reaction labels<select v-model="jev.labels"><option value="auto">Automatic when configured</option><option value="on">Enabled</option><option value="off">Disabled</option></select></label><label>Survey scoring engine<select v-model="jev.ssr_engine"><option value="embeddings">Embeddings</option><option value="jev">Jev</option></select></label></div>
          <div class="settings-help"><span>Applies to future operations.</span><InfoHint :theme="theme" label="Saving decision settings">Saving configures future operations. It does not send a test request or start an experiment.</InfoHint></div>
        </div>
        <p v-if="state.restart_required" class="settings-note" role="status">Restart the local MarketMirror service to refresh existing memory clients.</p>
        <p v-if="error" class="settings-error" role="alert">{{ error }}</p>
        <div v-if="tab !== 'connections'" class="settings-footer"><span v-if="saved" class="settings-saved" role="status"><Check :size="14" />Configuration saved</span><span v-else class="settings-note">Changes apply to new operations.</span><Button type="submit" :disabled="saving"><LoaderCircle v-if="saving" :size="15" class="settings-spin" />{{ saving ? 'Saving…' : 'Save changes' }}</Button></div>
      </form>
      <div v-else class="settings-error" role="alert">{{ error }}<Button variant="outline" @click="load">Retry</Button></div>
      </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
:global(.workspace-settings){width:min(940px,calc(100vw - 40px));max-width:940px!important;max-height:min(820px,90dvh);overflow:hidden;border-radius:22px!important;padding:0!important;color:var(--text);background:var(--panel)!important;border-color:var(--line)!important;gap:0!important;display:flex!important;flex-direction:column}.settings-header{flex-shrink:0;padding:25px 30px 23px;border-bottom:1px solid var(--line);flex-shrink:0}:global(.workspace-settings [data-slot=dialog-title]){font-size:20px;font-weight:600;line-height:1.4;letter-spacing:-.4px}:global(.workspace-settings [data-slot=dialog-description]){font-size:12px;line-height:1.7;color:var(--muted);margin-top:6px}.settings-body{display:grid;grid-template-columns:185px minmax(0,1fr);min-height:480px;overflow:hidden;flex:1}.settings-tabs{display:flex;flex-direction:column;gap:5px;padding:20px 12px;border-right:1px solid var(--line);background:var(--panel-2)}.settings-tabs button{display:flex;align-items:center;gap:10px;padding:12px;border:0;border-radius:10px;background:transparent;color:var(--muted);font-size:13px;line-height:1.5;text-align:left;cursor:pointer}.settings-main{padding:28px 32px 30px;overflow:auto;min-width:0;overscroll-behavior:contain}.settings-fields{display:grid;gap:21px}.settings-intro{margin-bottom:3px}.settings-intro h3{margin:0 0 7px;font-size:17px;letter-spacing:-.2px}.settings-intro p,.settings-note{margin:0;font-size:12px;line-height:1.75;color:var(--muted)}.settings-fields label{display:flex;flex-direction:column;gap:9px;font-size:13px;font-weight:550}.settings-fields input:not([type=checkbox]),.settings-fields select{width:100%;height:44px;border:1px solid var(--line);border-radius:10px;padding:0 13px;background:var(--panel);color:var(--text);font:inherit;font-size:13px;outline-offset:3px}.settings-fields input::placeholder{font-weight:400;color:var(--muted)}.settings-fields input:focus-visible,.settings-fields select:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.settings-switch{flex-direction:row!important;align-items:center;justify-content:space-between;gap:20px!important;padding:16px 0;border-top:1px solid var(--line)}.settings-switch span{display:grid;gap:6px}.settings-switch strong{font-size:13px;font-weight:550}.settings-switch small{color:var(--muted);font-size:12px;font-weight:400;line-height:1.7}.settings-switch input{width:18px;height:18px;flex-shrink:0;accent-color:var(--accent)}.settings-unavailable{padding:14px 16px;border:1px solid var(--line);border-radius:12px}.settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.settings-grid-three{grid-template-columns:repeat(3,1fr)}.settings-footer{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:30px;padding-top:22px;border-top:1px solid var(--line)}.settings-footer button{background:var(--accent);color:white;cursor:pointer;min-height:40px;padding:0 18px}.settings-status{display:flex;align-items:center;flex-wrap:wrap;gap:8px;font-size:12px;margin:0}.settings-status>span{width:6px;height:6px;border-radius:50%;background:#d8944f}.settings-status>span.ready{background:#51a482}.settings-status small{width:100%;color:var(--muted);font-size:12px;line-height:1.7}.settings-saved{display:flex;align-items:center;gap:6px;color:#388a67;font-size:12px}.settings-error{display:grid;gap:14px;color:#b84850;font-size:12px;line-height:1.7;margin-top:18px}.settings-loading{display:flex;align-items:center;justify-content:center;gap:12px;min-height:300px;color:var(--muted);font-size:13px}.settings-spin{animation:settings-spin 1s linear infinite}.settings-spend-summary{display:grid;grid-template-columns:1fr 1fr;gap:14px}.settings-spend-summary>div{display:grid;gap:9px;padding:17px;border:1px solid var(--line);border-radius:12px}.settings-spend-summary small,.settings-spend-summary span{font-size:12px;color:var(--muted);line-height:1.6}.settings-spend-summary strong{font-size:17px;font-weight:550}.settings-connection-row{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:20px 0;border-bottom:1px solid var(--line)}.settings-connection-row strong{font-size:13px;font-weight:550}.settings-connection-row p{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.7}.settings-connection-row button{flex-shrink:0;font-size:11px;cursor:pointer}@keyframes settings-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.settings-spin{animation:none}}@media(max-width:700px){:global(.workspace-settings){width:calc(100vw - 24px)}.settings-header{flex-shrink:0;padding:23px 24px}.settings-body{grid-template-columns:1fr;min-height:0}.settings-tabs{flex-direction:row;overflow-x:auto;border-right:0;border-bottom:1px solid var(--line);padding:10px 12px;flex-shrink:0}.settings-tabs button{white-space:nowrap;padding:10px 12px}.settings-main{padding:24px;max-height:calc(90dvh - 200px)}.settings-connection-row{flex-direction:column;gap:14px}}@media(max-width:480px){.settings-main{padding:22px 20px}.settings-grid{grid-template-columns:1fr}.settings-grid-three{grid-template-columns:repeat(3,1fr);gap:10px}.settings-spend-summary{grid-template-columns:1fr}.settings-footer>.settings-note{max-width:150px}}
.settings-help{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;color:var(--muted);font-size:12px;line-height:1.7}.settings-local-models{display:grid;gap:12px;padding:14px;border:1px solid var(--line);border-radius:12px}.settings-local-models>div{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px}.settings-local-models button{font-size:11px;cursor:pointer}
.settings-hosted-source{display:grid;gap:16px;padding:16px;border:1px solid var(--line);border-radius:12px}.settings-account-line{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}.settings-account-line a{color:var(--accent);text-decoration:underline;text-underline-offset:3px}.settings-source-options{display:flex;flex-wrap:wrap;gap:16px}.settings-source-options label{display:flex;flex-direction:row;align-items:center;gap:8px;font-size:13px}.settings-source-options input{width:16px!important;height:16px!important;accent-color:var(--accent)}
.settings-account-links{display:flex;gap:12px;flex-shrink:0}
</style>
