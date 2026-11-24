<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Brain, SlidersHorizontal, LoaderCircle, Check, ChevronRight, Cpu, Wallet, Plug, Wrench, Database, ShieldCheck } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog'
import { Button } from '../ui/button'
import InfoHint from './InfoHint.vue'
import LoadingSkeleton from './LoadingSkeleton.vue'
import ModelCards from './ModelCards.vue'
import './modal-controls.css'
import { api } from '../../workspace/api'
import { connectionsSummary, connectorStatus } from '../../workspace/connections.js'

const props = defineProps({ open: Boolean, theme: { type: String, default: 'light' }, initialTab: { type: String, default: 'models' }, initialProvider: { type: String, default: '' } })
const emit = defineEmits(['update:open', 'saved', 'connectors', 'models'])
const router = useRouter()
const tab = ref('models')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const state = ref(null)
const cloudAccount = ref(null)
const modelSource = ref('byok')
const hostedRemaining = computed(() => cloudAccount.value?.hosted_model ? Math.max(0, Number(cloudAccount.value.hosted_model.limit_usd) - Number(cloudAccount.value.hosted_model.used_or_reserved_usd || 0)) : 0)
async function loadCloudAccount(){cloudAccount.value=null;modelSource.value='byok';try{const response=await fetch('/auth/session',{credentials:'same-origin',headers:{Accept:'application/json'}});if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))return;const value=await response.json();if(value?.account&&typeof value.account.id==='string'&&value.account.id&&typeof value.account.email==='string'&&value.account.email&&typeof value.csrf==='string'&&value.csrf){const hosted=value.hosted_model;if(hosted&&!(typeof hosted.id==='string'&&hosted.id&&typeof hosted.label==='string'&&typeof hosted.limit_usd==='number'&&Number.isFinite(hosted.limit_usd)&&hosted.limit_usd>=0&&hosted.estimate===true))value.hosted_model=null;cloudAccount.value=value;modelSource.value=value.hosted_model&&state.value?.llm.model===value.hosted_model.id&&state.value?.llm.base_url?.includes('/hosted/v1')?'hosted':'byok'}}catch{}}
async function useHosted(){saving.value=true;error.value='';saved.value=false;try{const response=await fetch('/auth/use-hosted',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':cloudAccount.value.csrf,'X-MM-Workspace':cloudAccount.value.workspace?.id||''},body:'{}'});const value=await response.json();if(!response.ok||value.success!==true)throw new Error(value.error||'Could not select the MarketMirror model.');hydrate(await api('/api/workspace/settings'));await loadCloudAccount();saved.value=true;emit('saved',state.value)}catch(err){error.value=err.message}finally{saving.value=false}}
const spending = ref({ process_limit_usd: 0, input_price_usd_per_mtok: '', output_price_usd_per_mtok: '' })
const tabs = [
  { id: 'models', label: 'Models', icon: Cpu, help: 'Which AI model answers in chat and plays the simulated people.' },
  { id: 'spending', label: 'Spending', icon: Wallet, help: 'A ceiling on estimated model costs, so a run cannot surprise you.' },
  { id: 'memory', label: 'Memory', icon: Brain, help: 'Where simulated people keep what they read and did.' },
  { id: 'jev', label: 'Decision engine', icon: SlidersHorizontal, help: 'An outside model that labels reactions and scores survey answers.' },
  { id: 'connections', label: 'Connections', icon: Plug, help: 'MCP servers, data imports and MarketMirror in your other AI apps.' }
]
const current = computed(() => tabs.find(item => item.id === tab.value) || tabs[0])
const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(value || 0)
const memory = ref({ backend: 'local', embeddings: false, extract_activity: false, cognee_url: '', zep_api_key: '' })
const jev = ref({ route: 'typesafe', model: '', parallel: 4, timeout: 60, retries: 3, labels: 'auto', ssr_engine: 'embeddings', api_key: '' })
const connectors = ref([]), models = ref([]), connectionsLoading = ref(false)
const summary = computed(() => connectionsSummary(connectors.value, models.value))
async function loadConnections() {
  connectionsLoading.value = true
  const [c, m] = await Promise.allSettled([api('/api/workspace/connectors'), api('/api/workspace/models')])
  connectors.value = c.status === 'fulfilled' ? c.value : []
  models.value = m.status === 'fulfilled' ? m.value.models || [] : []
  connectionsLoading.value = false
}
function hydrate(value) {
  state.value = value
  spending.value = { process_limit_usd: value.spending?.process_limit_usd || 0, input_price_usd_per_mtok: value.spending?.input_price_usd_per_mtok ?? '', output_price_usd_per_mtok: value.spending?.output_price_usd_per_mtok ?? '' }
  memory.value = { ...memory.value, ...value.memory, zep_api_key: '' }
  jev.value = { ...jev.value, ...value.jev, api_key: '' }
}
async function load() {
  loading.value = true; error.value = ''; saved.value = false
  try { hydrate(await api('/api/workspace/settings')); await loadCloudAccount() } catch (err) { error.value = err.message }
  finally { loading.value = false }
}
function choose(id) { tab.value = id; saved.value = false; error.value = ''; if (id === 'connections') loadConnections() }
watch(() => props.open, value => { if (value) { choose(tabs.some(item => item.id === props.initialTab) ? props.initialTab : 'models'); load() } }, { immediate: true })
function modelsSaved(value) { hydrate(value); emit('saved', value) }
function openConnections() { emit('update:open', false); emit('connectors'); router.push('/workspace/connectors') }
async function save() {
  saving.value = true; error.value = ''; saved.value = false
  try {
    const bodies = {
      memory: { backend: memory.value.backend, embeddings: memory.value.embeddings, extract_activity: memory.value.extract_activity, ...(memory.value.backend === 'cognee' ? { cognee_url: memory.value.cognee_url } : {}), zep_api_key: memory.value.zep_api_key },
      jev: { route: jev.value.route, model: jev.value.model, parallel: Number(jev.value.parallel), timeout: Number(jev.value.timeout), retries: Number(jev.value.retries), labels: jev.value.labels, ssr_engine: jev.value.ssr_engine, api_key: jev.value.api_key },
      spending: { process_limit_usd: Number(spending.value.process_limit_usd), input_price_usd_per_mtok: spending.value.input_price_usd_per_mtok === '' ? null : Number(spending.value.input_price_usd_per_mtok), output_price_usd_per_mtok: spending.value.output_price_usd_per_mtok === '' ? null : Number(spending.value.output_price_usd_per_mtok) },
    }
    hydrate(await api('/api/workspace/settings', { method: 'PUT', body: { [tab.value]: bodies[tab.value] } }))
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
        <DialogDescription>Models, spending, memory and connections for this computer.</DialogDescription>
      </DialogHeader>
      <div class="settings-body">
      <nav class="settings-tabs workspace-modal-tabs" aria-label="Settings sections">
        <button v-for="item in tabs" :key="item.id" type="button" :class="{ active: tab === item.id }" :aria-pressed="tab === item.id" @click="choose(item.id)"><component :is="item.icon" :size="16" aria-hidden="true" />{{ item.label }}</button>
      </nav>
      <label class="settings-tab-select"><span class="ws-sr-only">Settings section</span><select :value="tab" @change="choose($event.target.value)"><option v-for="item in tabs" :key="item.id" :value="item.id">{{ item.label }}</option></select><ChevronRight :size="15" aria-hidden="true" /></label>
      <div class="settings-main">
      <div class="settings-intro"><h3>{{ current.label }}</h3><p>{{ current.help }}</p></div>
      <LoadingSkeleton v-if="loading" class="ws-dialog-skeleton" :lines="4" label="Loading your configuration" />
      <div v-else-if="!state" class="settings-error" role="alert">{{ error }}<Button variant="outline" @click="load">Retry</Button></div>

      <div v-else-if="tab === 'models'" class="settings-fields">
        <div v-if="cloudAccount" class="mm-conn-card settings-hosted-source"><div class="settings-account-line"><span>{{ cloudAccount.account.email }}</span><span class="settings-account-links"><a href="/team">Team</a><a href="/account">Account</a></span></div><div class="settings-source-options"><label v-if="cloudAccount.hosted_model"><input type="radio" name="model-source" :checked="modelSource === 'hosted'" @change="modelSource = 'hosted'" /><span>MarketMirror model</span></label><label><input type="radio" name="model-source" :checked="modelSource === 'byok'" @change="modelSource = 'byok'" /><span>Your API key / model</span></label></div><div v-if="modelSource === 'hosted' && cloudAccount.hosted_model" class="settings-help"><span>{{ cloudAccount.hosted_model.label }} · {{ money(hostedRemaining) }} estimated allowance left</span><InfoHint :theme="theme" label="MarketMirror model allowance">{{ money(cloudAccount.hosted_model.used_or_reserved_usd || 0) }} used or reserved of {{ money(cloudAccount.hosted_model.limit_usd) }}. This is an estimated usage allowance. Reservations may include pending or failed calls; it is not a billing balance or invoice.</InfoHint></div><Button v-if="modelSource === 'hosted' && cloudAccount.hosted_model" size="sm" :disabled="saving" @click="useHosted">Use the MarketMirror model</Button></div>
        <ModelCards v-if="modelSource === 'byok'" :key="initialProvider" :state="state" :theme="theme" :initial-provider="initialProvider" @saved="modelsSaved" />
        <p v-if="error" class="settings-error" role="alert">{{ error }}</p>
      </div>

      <div v-else-if="tab === 'connections'" class="settings-fields">
        <LoadingSkeleton v-if="connectionsLoading && !connectors.length" :lines="2" label="Checking connections" />
        <template v-else>
          <div class="settings-stats">
            <div class="mm-conn-card"><small>MCP servers</small><strong>{{ summary.connected }} <span>of {{ summary.servers }} connected</span></strong><span v-if="summary.failing" class="mm-badge error">{{ summary.failing }} need attention</span><span v-else-if="summary.servers" class="mm-badge ok">All fine</span><span v-else class="mm-badge idle">None added</span></div>
            <div class="mm-conn-card"><small>Tools on in chat</small><strong>{{ summary.toolsOn }}</strong><span class="mm-badge plain">Read-only only</span></div>
            <div class="mm-conn-card"><small>Models ready</small><strong>{{ summary.modelsReady }}</strong><button type="button" class="settings-link" @click="choose('models')">See models</button></div>
          </div>
          <ul v-if="connectors.length" class="settings-conn-list">
            <li v-for="c in connectors" :key="c.id"><span class="mm-conn-icon"><Plug :size="16" aria-hidden="true" /></span><span><b>{{ c.name }}</b><small>{{ c.tools.length }} {{ c.tools.length === 1 ? 'tool' : 'tools' }}{{ c.enabled ? ' · on in chat' : ' · off in chat' }}</small></span><span class="mm-badge" :class="connectorStatus(c).tone">{{ connectorStatus(c).label }}</span></li>
          </ul>
          <div class="mm-conn-card settings-conn-cta"><div><b>Manage connections</b><p class="mm-conn-help">Add MCP servers, test them, choose their tools, import analytics and ads, and add MarketMirror to Claude, Cursor and other apps.</p></div><Button @click="openConnections">Open Connections<ChevronRight :size="15" /></Button></div>
        </template>
      </div>

      <form v-else class="settings-form" @submit.prevent="save">
        <div v-if="tab === 'spending'" class="settings-fields">
          <div class="settings-stats">
            <div class="mm-conn-card"><small>Spent since the app started</small><strong>{{ money(state.spending.process_spent_usd) }}</strong><span class="mm-conn-help">{{ state.spending.process_calls }} model {{ state.spending.process_calls === 1 ? 'call' : 'calls' }}</span></div>
            <div class="mm-conn-card"><small>Current run budget</small><strong>{{ state.spending.run_cap ? money(state.spending.run_cap.spent_usd) + ' of ' + money(state.spending.run_cap.limit_usd) : 'None' }}</strong><span class="mm-conn-help">{{ state.spending.run_cap?.label || 'Set a budget when you start a test.' }}</span></div>
          </div>
          <div class="mm-conn-card settings-group">
            <label class="mm-field">Stop at this estimated spend (USD)<input v-model="spending.process_limit_usd" class="mm-input" type="number" min="0" max="1000000" step="any" required inputmode="decimal" /><small>New model calls stop once the estimate reaches this. 0 means no limit. Resets when the app restarts.</small></label>
            <div class="settings-help"><span>Calls already running can go slightly over.</span><InfoHint :theme="theme" label="How the limit works">{{ state.spending.enforcement }}</InfoHint></div>
          </div>
          <details class="mm-advanced"><summary><ChevronRight aria-hidden="true" />Advanced: prices used for the estimate</summary><div>
            <p class="mm-conn-help">USD per million tokens. Leave blank to use the built-in price list for your model.</p>
            <div class="settings-grid"><label class="mm-field">Input tokens<input v-model="spending.input_price_usd_per_mtok" class="mm-input" type="number" min="0" max="1000000" step="any" placeholder="Built-in price" /></label><label class="mm-field">Output tokens<input v-model="spending.output_price_usd_per_mtok" class="mm-input" type="number" min="0" max="1000000" step="any" placeholder="Built-in price" /></label></div>
            <p class="mm-conn-help">These are estimates and may differ from your invoice. They do not set a limit at your provider.</p>
          </div></details>
        </div>

        <div v-else-if="tab === 'memory'" class="settings-fields">
          <fieldset class="settings-choices"><legend class="ws-sr-only">Memory provider</legend>
            <label v-for="item in state.memory.providers" :key="item.id" class="mm-conn-card settings-choice" :class="{ 'is-active': memory.backend === item.id, disabled: !item.supported }"><input v-model="memory.backend" type="radio" name="memory-backend" :value="item.id" :disabled="!item.supported" /><span><span class="mm-conn-title"><b>{{ item.label }}</b><span v-if="!item.supported" class="mm-badge idle">Not available</span><span v-else-if="item.id === state.memory.backend" class="mm-badge accent">In use</span></span><small>{{ item.description }}</small></span></label>
          </fieldset>
          <label v-if="memory.backend === 'cognee'" class="mm-field">Cognee service address<input v-model="memory.cognee_url" class="mm-input" type="url" placeholder="http://localhost:8000" /></label>
          <div v-if="memory.backend === 'zep'" class="mm-field"><label for="settings-zep">Zep API key</label><input id="settings-zep" v-model="memory.zep_api_key" class="mm-input" type="password" autocomplete="new-password" :placeholder="state.memory.zep_key_configured ? 'Saved. Leave blank to keep it' : 'Paste your Zep API key'" /></div>
          <div class="mm-conn-card settings-group settings-switches">
            <label class="settings-switch"><span><strong>Find related memories by meaning</strong><small>Uses free local embeddings, not just matching words.</small></span><input v-model="memory.embeddings" type="checkbox" /></label>
            <label class="settings-switch"><span><strong>Learn from what people did</strong><small>Turns simulation activity into memory during new runs. Costs extra model calls.</small></span><input v-model="memory.extract_activity" type="checkbox" /></label>
          </div>
        </div>

        <div v-else class="settings-fields">
          <div class="mm-conn-card settings-status-card"><ShieldCheck :size="18" aria-hidden="true" /><div><span class="mm-conn-title"><b>Jev</b><span class="mm-badge" :class="state.jev.configured ? 'ok' : 'idle'">{{ state.jev.configured ? 'Key saved' : 'Not set up' }}</span></span><p class="mm-conn-help">{{ state.jev.reason || 'Optional. Without it, simpler built-in scoring is used.' }}</p></div></div>
          <div class="mm-conn-card settings-group">
            <div class="settings-grid"><label class="mm-field">Connect through<select v-model="jev.route" class="mm-input"><option value="typesafe">Typesafe (direct)</option><option value="openrouter">OpenRouter</option></select></label><label class="mm-field">Model<input v-model="jev.model" class="mm-input" placeholder="Default" /></label></div>
            <div class="mm-field"><label for="settings-jev-key">API key</label><input id="settings-jev-key" v-model="jev.api_key" class="mm-input" type="password" autocomplete="new-password" :placeholder="state.jev.key_configured ? 'Saved. Leave blank to keep it' : 'Paste a key for the route above'" /><small v-if="jev.route === 'openrouter'">Shared with other OpenRouter features on this computer.</small></div>
          </div>
          <div class="mm-conn-card settings-group">
            <div class="settings-grid"><label class="mm-field">Label reactions<select v-model="jev.labels" class="mm-input"><option value="auto">When a key is set</option><option value="on">Always</option><option value="off">Never</option></select></label><label class="mm-field">Score survey answers with<select v-model="jev.ssr_engine" class="mm-input"><option value="embeddings">Local embeddings (free)</option><option value="jev">Jev</option></select></label></div>
          </div>
          <details class="mm-advanced"><summary><ChevronRight aria-hidden="true" />Advanced: speed and retries</summary><div>
            <div class="settings-grid settings-grid-three"><label class="mm-field">Parallel requests<input v-model="jev.parallel" class="mm-input" type="number" min="1" max="32" required /></label><label class="mm-field">Timeout (seconds)<input v-model="jev.timeout" class="mm-input" type="number" min="5" max="600" required /></label><label class="mm-field">Retries<input v-model="jev.retries" class="mm-input" type="number" min="0" max="8" required /></label></div>
          </div></details>
        </div>
        <p v-if="state.restart_required" class="settings-note" role="status">Restart MarketMirror to use the new memory settings.</p>
        <p v-if="error" class="settings-error" role="alert">{{ error }}</p>
        <div class="settings-footer"><span v-if="saved" class="settings-saved" role="status"><Check :size="14" />Saved</span><span v-else class="settings-note">Changes apply to new chats and runs. Saving makes no model call.</span><Button type="submit" :disabled="saving"><LoaderCircle v-if="saving" :size="15" class="settings-spin" />{{ saving ? 'Saving…' : 'Save changes' }}</Button></div>
      </form>
      </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
:global(.workspace-settings){width:min(960px,calc(100vw - 40px));max-width:960px!important;max-height:min(840px,92dvh);overflow:hidden;border-radius:22px!important;padding:0!important;color:var(--text);background:var(--panel)!important;border-color:var(--line)!important;gap:0!important;display:flex!important;flex-direction:column}
.settings-header{flex-shrink:0;padding:24px 30px 20px;border-bottom:1px solid var(--line)}
:global(.workspace-settings [data-slot=dialog-title]){font-size:20px;font-weight:600;line-height:1.4;letter-spacing:-.4px}
:global(.workspace-settings [data-slot=dialog-description]){font-size:12.5px;line-height:1.6;color:var(--muted);margin-top:4px}
.settings-body{display:grid;grid-template-columns:190px minmax(0,1fr);min-height:500px;overflow:hidden;flex:1}
.settings-tabs{display:flex;flex-direction:column;gap:4px;padding:18px 12px;border-right:1px solid var(--line);background:var(--panel-2)}
.settings-tabs button{display:flex;align-items:center;gap:10px;padding:11px 12px;border:0;border-radius:10px;background:transparent;color:var(--muted);font-size:13px;line-height:1.5;text-align:left;cursor:pointer}
.settings-tab-select{display:none}
.settings-main{padding:24px 30px 28px;overflow:auto;min-width:0;overscroll-behavior:contain}
.settings-intro{margin-bottom:18px}
.settings-intro h3{margin:0 0 4px;font-size:17px;font-weight:600;letter-spacing:-.2px}
.settings-intro p,.settings-note{margin:0;font-size:12.5px;line-height:1.65;color:var(--muted)}
.settings-fields{display:grid;gap:14px}
.settings-group{display:grid;gap:14px}
.settings-help{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;color:var(--muted);font-size:12px;line-height:1.65}
.settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.settings-grid-three{grid-template-columns:repeat(3,1fr)}
.settings-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.settings-stats>div{display:grid;gap:6px;align-content:start}
.settings-stats small{font-size:12px;color:var(--muted)}
.settings-stats strong{font-size:20px;font-weight:600;letter-spacing:-.3px}
.settings-stats strong span{font-size:12.5px;font-weight:400;color:var(--muted)}
.settings-stats .mm-badge{justify-self:start}
.settings-link{justify-self:start;border:0;background:transparent;padding:0;color:var(--accent);font-size:12.5px;text-decoration:underline;text-underline-offset:3px;cursor:pointer;min-height:24px}
.settings-conn-list{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.settings-conn-list li{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
.settings-conn-list li>span:nth-child(2){flex:1;min-width:0;display:grid}
.settings-conn-list b{font-size:13px;font-weight:600;overflow-wrap:anywhere}
.settings-conn-list small{font-size:12px;color:var(--muted)}
.settings-conn-list .mm-conn-icon{width:30px;height:30px}
.settings-conn-cta{display:flex;align-items:center;justify-content:space-between;gap:16px}
.settings-conn-cta b{font-size:13.5px}
.settings-conn-cta>button{flex-shrink:0}
.settings-choices{display:grid;gap:8px;border:0;margin:0;padding:0}
.settings-choice{display:flex;gap:12px;align-items:flex-start;cursor:pointer;padding:12px 14px}
.settings-choice input{width:16px;height:16px;margin-top:2px;accent-color:var(--accent);flex-shrink:0}
.settings-choice>span{display:grid;gap:4px;min-width:0}
.settings-choice b{font-size:13.5px;font-weight:600}
.settings-choice small{font-size:12px;line-height:1.6;color:var(--muted)}
.settings-choice.disabled{opacity:.6;cursor:not-allowed}
.settings-choice:focus-within{outline:2px solid var(--accent);outline-offset:2px}
.settings-switches{gap:0;padding-top:4px;padding-bottom:4px}
.settings-switch{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:12px 0;cursor:pointer}
.settings-switch+.settings-switch{border-top:1px solid var(--line)}
.settings-switch span{display:grid;gap:4px}
.settings-switch strong{font-size:13px;font-weight:550}
.settings-switch small{color:var(--muted);font-size:12px;font-weight:400;line-height:1.6}
.settings-switch input{width:18px;height:18px;flex-shrink:0;accent-color:var(--accent)}
.settings-status-card{display:flex;gap:12px;align-items:flex-start}
.settings-status-card>svg{color:var(--accent);flex-shrink:0;margin-top:2px}
.settings-footer{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:22px;padding-top:18px;border-top:1px solid var(--line)}
.settings-footer button{background:var(--accent);color:var(--primary-foreground,#fff);cursor:pointer;min-height:40px;padding:0 18px}
.settings-saved{display:flex;align-items:center;gap:6px;color:var(--yes);font-size:12.5px}
.settings-error{display:grid;gap:14px;color:var(--no);font-size:12.5px;line-height:1.7;margin-top:14px}
.settings-spin{animation:settings-spin 1s linear infinite}
@keyframes settings-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.settings-spin{animation:none}}
.settings-hosted-source{display:grid;gap:14px}
.settings-account-line{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
.settings-account-line a{color:var(--accent);text-decoration:underline;text-underline-offset:3px}
.settings-account-links{display:flex;gap:12px;flex-shrink:0}
.settings-source-options{display:flex;flex-wrap:wrap;gap:16px}
.settings-source-options label{display:flex;align-items:center;gap:8px;font-size:13px}
.settings-source-options input{width:16px;height:16px;accent-color:var(--accent)}
.settings-fields button:focus-visible,.settings-tabs button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:760px){
  :global(.workspace-settings){width:calc(100vw - 16px);max-height:94dvh;border-radius:18px!important}
  .settings-header{padding:18px 18px 14px}
  .settings-body{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr);min-height:0}
  .settings-tabs{display:none}
  .settings-tab-select{display:flex;align-items:center;position:relative;margin:12px 16px 0}
  .settings-tab-select select{width:100%;height:44px;padding:0 36px 0 14px;border:1px solid var(--line)!important;border-radius:10px;background:var(--panel-2)!important;color:var(--text);font-size:14px;font-weight:550;appearance:none}
  .settings-tab-select select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .settings-tab-select svg{position:absolute;right:14px;transform:rotate(90deg);pointer-events:none;color:var(--muted)}
  .settings-main{padding:16px 16px 22px}
  .settings-grid,.settings-grid-three{grid-template-columns:1fr}
  .settings-conn-cta{flex-direction:column;align-items:stretch}
  .settings-footer{flex-direction:column;align-items:stretch;gap:12px}
}
</style>
