<template>
  <Dialog :open="open" @update:open="$emit('update:open',$event)">
    <DialogContent class="ws-overlay connections-dialog sm:max-w-2xl" :data-theme="theme">
      <DialogHeader class="connections-header"><DialogTitle>Connect your tools</DialogTitle><DialogDescription>Bring your data and models into the conversation.</DialogDescription></DialogHeader>
      <div class="connection-tabs workspace-modal-tabs" role="tablist" aria-label="Connection category" @keydown="navigateTabs"><Button role="tab" :id="`${tabId}-data`" :aria-selected="tab === 'data'" :aria-controls="`${tabId}-panel`" :tabindex="tab === 'data' ? 0 : -1" :variant="tab === 'data' ? 'secondary' : 'ghost'" @click="tab='data'"><Database />Data sources</Button><Button role="tab" :id="`${tabId}-models`" :aria-selected="tab === 'models'" :aria-controls="`${tabId}-panel`" :tabindex="tab === 'models' ? 0 : -1" :variant="tab === 'models' ? 'secondary' : 'ghost'" @click="tab='models'"><Bot />Model providers</Button><Button role="tab" :id="`${tabId}-mcp`" :aria-selected="tab === 'mcp'" :aria-controls="`${tabId}-panel`" :tabindex="tab === 'mcp' ? 0 : -1" :variant="tab === 'mcp' ? 'secondary' : 'ghost'" @click="tab='mcp'"><Plug />MCP servers</Button></div>
      <div class="connections-body" role="tabpanel" :id="`${tabId}-panel`" :aria-labelledby="`${tabId}-${tab}`" tabindex="0">
      <p v-if="error" class="connection-error" role="alert">{{ error }}</p><p v-if="notice" class="connection-notice" role="status">{{ notice }}</p>
      <div v-if="tab === 'data'" class="connection-list">
        <label class="connection-search"><Search :size="16" /><input v-model="search" type="search" placeholder="Find analytics, ads or documents" aria-label="Search data sources" /></label>
        <div class="connection-row"><span class="connection-icon"><FolderOpen /></span><div><b>Saved experiments</b><p>{{ runs.length }} saved runs with reports, responses and persona activity.</p></div><Button variant="outline" size="sm" @click="$emit('choose-run');$emit('update:open',false)">Choose run</Button></div>
        <div v-for="c in filteredSources" :key="c.name" class="connection-row"><span class="connection-icon" :style="{color:c.color,background:c.tint}"><BrandIcon v-if="c.brand" :brand="c.brand" :size="20" /><component v-else :is="c.icon" /></span><div><b>{{ c.name }}</b><p>{{ c.description }}</p></div><Button v-if="c.name === 'Meta Ads' || c.name === 'Google Analytics'" variant="ghost" size="sm" @click="preset(c.name)">Connect MCP</Button><Button variant="outline" size="sm" @click="attach">Add files</Button></div>
        <p v-if="!filteredSources.length" class="connection-note">No matching sources. Try analytics, ads or documents.</p>
        <p class="connection-note">Add CSV, JSON or text exports as conversation context. Choose several files to compare sources together.</p>
      </div>
      <div v-else-if="tab === 'mcp'" class="connection-list">
        <p class="connection-note">Connect a remote MCP server, check its tools, then choose which read-only tools chat may use. Connections in other AI apps are separate.</p>
        <div class="mcp-presets"><Button variant="outline" size="sm" @click="preset('Meta Ads')">Meta / Facebook Ads</Button><Button variant="outline" size="sm" @click="preset('Google Analytics')">Google Analytics</Button><Button variant="ghost" size="sm" @click="preset('Custom MCP')">Custom server</Button></div>
        <form v-if="showMcpForm || !connectors.length" class="mcp-form" @submit.prevent="saveConnector">
          <div class="mcp-form-title"><b>{{ editing ? 'Edit MCP server' : 'Add an MCP server' }}</b><button v-if="editing" type="button" @click="preset('Custom MCP')">New server</button></div>
          <p v-if="presetNote" class="connection-note">{{ presetNote }}</p>
          <a v-if="presetDocs" :href="presetDocs" target="_blank" rel="noopener noreferrer" class="mcp-docs">Provider setup documentation ↗</a>
          <label>Name<input v-model="draft.name" required maxlength="100" placeholder="Analytics or ads workspace" /></label>
          <label>HTTPS MCP endpoint<input v-model="draft.url" type="url" required placeholder="https://your-server.example/mcp" /></label>
          <label>Bearer access token<input v-model="draft.token" type="password" autocomplete="new-password" :placeholder="editing ? 'Leave blank to retain the saved token' : 'Required if your server needs authentication'" /></label>
          <label>Streamable HTTP protocol<select v-model="draft.protocol_version"><option value="2025-11-25">2025-11-25</option><option value="2025-06-18">2025-06-18</option></select></label>
          <p class="connection-note">Public HTTPS servers only. Tokens stay on the server. OAuth sign-in, local stdio servers and newer protocol-only endpoints require a compatible bridge.</p>
          <Button type="submit" :disabled="!!connecting">{{ connecting === 'save-mcp' ? 'Saving…' : 'Save server' }}</Button>
        </form>
        <label v-if="connectors.some(c => c.tools.length)" class="connection-search"><Search :size="16" /><input v-model="toolSearch" type="search" placeholder="Search discovered tools" aria-label="Search discovered tools" /></label>
        <div v-for="c in connectors" :key="c.id" class="mcp-server">
          <div class="connection-row"><span class="connection-icon"><BrandIcon v-if="connectorBrand(c)" :brand="connectorBrand(c)" :size="20" /><Plug v-else /></span><div><b>{{ c.name }}</b><p>{{ c.status === 'connected' ? `${c.tools.length} tools discovered` : ['error', 'auth_required'].includes(c.status) ? c.error : 'Saved · connection not checked' }}</p><p class="mcp-endpoint">{{ c.url }}</p></div><Button variant="outline" size="sm" :disabled="!!connecting" @click="discoverConnector(c)">{{ connecting === c.id ? 'Checking…' : 'Check connection' }}</Button></div>
          <div class="mcp-controls"><label><input type="checkbox" :checked="c.enabled" :disabled="updatingConnector === c.id" @change="patchConnector(c, { enabled: $event.target.checked })" />Allow selected tools in chat</label><button type="button" @click="editConnector(c)">Edit</button><button type="button" @click="deleteConnector(c)">Remove</button></div>
          <p v-if="c.checked_at" class="connection-note">Last checked {{ new Date(c.checked_at * 1000).toLocaleString() }}. A saved check does not guarantee the account remains available.</p>
          <details v-if="c.tools.length" open class="mcp-tools"><summary>Tools for chat · {{ c.allowed_tools.length }} selected / {{ c.tools.length }} discovered</summary><p v-if="!visibleTools(c).length" class="connection-note">No tools match your search.</p><label v-for="tool in visibleTools(c)" :key="tool.name"><input type="checkbox" :checked="c.allowed_tools.includes(tool.name)" :disabled="!tool.read_only || !!connecting || updatingConnector === c.id" @change="toggleTool(c, tool.name, $event.target.checked)" /><span><b>{{ tool.name }}</b><small>{{ tool.description }}</small><small v-if="!tool.read_only">Unavailable: server does not declare this tool read-only.</small></span></label></details>
          <p v-if="c.tools_truncated" class="connection-note">Tool discovery reached its page or size limit. Only listed tools are available.</p>
        </div>
        <p v-if="!connectors.length" class="connection-note">No MCP servers saved yet.</p>
      </div>
      <div v-else class="connection-list provider-list">
        <label class="connection-search"><Search :size="16" /><input v-model="modelSearch" type="search" placeholder="Find a provider or your own model" aria-label="Search model providers" /></label>
        <p v-if="loading" class="connection-note" role="status">Checking model configuration…</p>
        <template v-if="connectedLogins.length"><h3 class="provider-group">Connected on this server</h3><div v-for="login in connectedLogins" :key="login.id" class="connection-row provider-row"><span class="connection-icon"><BrandIcon v-if="brandFor(login.id)" :brand="brandFor(login.id)" :size="20" /><span v-else class="provider-initial">{{ login.label.slice(0, 1) }}</span></span><div><b>{{ login.label }}</b><p>Gateway running · available in the chat model selector</p></div><span class="provider-connected">Connected</span></div></template>
        <template v-if="cloudProviders.length"><h3 class="provider-group">Cloud API · bring your own key</h3>
        <p class="provider-caption">Your provider account, model and API key. Choose an available model identifier in settings.</p>
        <div v-for="p in cloudProviders" :key="p.id" class="connection-row provider-row"><span class="connection-icon"><BrandIcon v-if="brandFor(p.id)" :brand="brandFor(p.id)" :size="20" /><span v-else class="provider-initial">{{ p.label.slice(0, 1) }}</span></span><div><b>{{ p.label }}</b><p>{{ hasKey(p) ? 'API credentials saved' : 'Add your API key and model' }}</p></div><Button variant="outline" size="sm" @click="configureModel(p.id)">{{ hasKey(p) ? 'Edit' : 'Set up' }}</Button></div>
        </template>
        <template v-if="selfHostedProviders.length"><h3 class="provider-group">Self-hosted & custom models</h3>
        <p class="provider-caption">Connect Ollama, vLLM, LM Studio or another OpenAI-compatible server using its URL and model identifier.</p>
        <div v-for="p in selfHostedProviders" :key="p.id" class="connection-row provider-row"><span class="connection-icon"><BrandIcon v-if="brandFor(p.id)" :brand="brandFor(p.id)" :size="20" /><span v-else class="provider-initial">{{ p.id === 'compatible' ? 'AI' : p.label.slice(0,1) }}</span></span><div><b>{{ p.id === 'compatible' ? 'Your own model / API endpoint' : p.label }}</b><p>{{ p.id === 'compatible' ? 'Custom server URL, model name and optional token' : 'Use a model installed on your Ollama server' }}</p></div><Button variant="outline" size="sm" @click="configureModel(p.id)">Configure</Button></div>
        </template>
        <details v-if="availableLogins.length" class="api-connections"><summary>Existing server logins</summary><p class="connection-note">These CLIs run on the MarketMirror server. Your browser’s personal subscriptions are not automatically connected.</p><div v-for="login in availableLogins" :key="login.id" class="connection-row provider-row"><span class="connection-icon"><BrandIcon v-if="brandFor(login.id)" :brand="brandFor(login.id)" :size="20" /><span v-else class="provider-initial">{{ login.label.slice(0,1) }}</span></span><div><b>{{ login.label }}</b><p>{{ login.installed ? 'Installed on this server · uses its existing login' : 'Not installed on this server' }}</p></div><Button variant="outline" size="sm" :disabled="!login.installed || !!connecting" @click="connectLogin(login)">{{ connecting === login.id ? 'Connecting…' : 'Connect' }}</Button></div></details>
        <p v-if="!loading && !cloudProviders.length && !selfHostedProviders.length && !connectedLogins.length && !availableLogins.length" class="connection-note">{{ modelSearch.trim() ? 'No providers match your search.' : error ? 'The provider list could not be loaded.' : 'No model providers are configured.' }}</p>
      </div>
      </div>
      <DialogFooter class="connections-footer"><Button variant="ghost" @click="configureModel('')"><Settings2 />Model settings</Button><Button @click="$emit('update:open',false)">Done</Button></DialogFooter>
    </DialogContent>
  </Dialog>
</template>
<script setup>
import { computed, ref, watch, useId, nextTick } from 'vue'
import { Bot, Database, FileText, FolderOpen, ChartNoAxesCombined, ContactRound, Plug, Settings2, Search, MousePointerClick, Megaphone } from 'lucide-vue-next'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog'
import BrandIcon from '../BrandIcon.vue'
import './modal-controls.css'
import { api } from '../../workspace/api.js'
const props = defineProps({open:Boolean,theme:{type:String,default:'light'},runs:{type:Array,default:()=>[]},initialTab:{type:String,default:'data'}})
const emit = defineEmits(['update:open','attach','choose-run','connected','configure-model'])
const toolSearch=ref(''),showMcpForm=ref(false),updatingConnector=ref('')
function brandFor(id){return ({claude:'anthropic',anthropic:'anthropic',gemini:'googlegemini',ollama:'ollama'})[id] || ''}
function connectorBrand(c){return c.url.startsWith('https://mcp.facebook.com/')?'meta':c.name==='Google Analytics'?'googleanalytics':''}
function visibleTools(c){const query=toolSearch.value.trim().toLowerCase();return c.tools.filter(tool=>`${tool.name} ${tool.description}`.toLowerCase().includes(query))}
const connectors=ref([]),editing=ref(''),presetNote=ref(''),presetDocs=ref('')
const draft=ref({name:'',url:'',token:'',protocol_version:'2025-11-25'})
function preset(name){showMcpForm.value=true;tab.value='mcp';editing.value='';draft.value={name:name==='Custom MCP'?'':name,url:name==='Meta Ads'?'https://mcp.facebook.com/ads':'',token:'',protocol_version:'2025-11-25'};presetNote.value=name==='Meta Ads'?'Use a Meta user or employee-role system-user access token with ads_mcp_management and ads_read permissions. This form uses bearer authentication; it does not run Facebook OAuth.':name==='Google Analytics'?'Google provides an open-source Analytics MCP server. Deploy a compatible public HTTPS bridge and enter its endpoint; no Google-hosted endpoint is preconfigured.':'';presetDocs.value=name==='Meta Ads'?'https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-get-started':name==='Google Analytics'?'https://developers.google.com/analytics/devguides/MCP':''}
function editConnector(c){showMcpForm.value=true;editing.value=c.id;draft.value={name:c.name,url:c.url,token:'',protocol_version:c.protocol_version};presetNote.value='';presetDocs.value=''}
async function saveConnector(){connecting.value='save-mcp';error.value='';notice.value='';try{await api('/api/workspace/connectors'+(editing.value?'/'+editing.value:''),{method:editing.value?'PATCH':'POST',body:draft.value});draft.value.token='';await loadConnectors();showMcpForm.value=false;editing.value='';notice.value='Server saved. Check its connection to discover available tools.';emit('connected')}catch(e){error.value=e.message}finally{connecting.value=''}}
async function loadConnectors(){connectors.value=await api('/api/workspace/connectors')}
async function patchConnector(c,body){updatingConnector.value=c.id;error.value='';try{await api('/api/workspace/connectors/'+c.id,{method:'PATCH',body});await loadConnectors();emit('connected')}catch(e){error.value=e.message;await loadConnectors().catch(()=>{})}finally{updatingConnector.value=''}}
async function discoverConnector(c){connecting.value=c.id;error.value='';notice.value='';try{const result=await api('/api/workspace/connectors/'+c.id+'/discover',{method:'POST',body:{}});await loadConnectors();if(result.status==='connected')notice.value='Tools discovered. Select the read-only tools you want chat to use.';else error.value=result.error;emit('connected')}catch(e){error.value=e.message}finally{connecting.value=''}}
async function deleteConnector(c){error.value='';try{await api('/api/workspace/connectors/'+c.id,{method:'DELETE'});await loadConnectors();emit('connected')}catch(e){error.value=e.message}}
function toggleTool(c,name,on){patchConnector(c,{allowed_tools:on?[...c.allowed_tools,name]:c.allowed_tools.filter(item=>item!==name)})}
const modelSearch=ref('')
function matchesModel(item){return `${item.label} ${item.id}`.toLowerCase().includes(modelSearch.value.trim().toLowerCase())}
const cloudProviders=computed(()=>(state.value.api_providers||[]).filter(p=>!['ollama','compatible'].includes(p.id)&&matchesModel(p)))
const selfHostedProviders=computed(()=>(state.value.api_providers||[]).filter(p=>['ollama','compatible'].includes(p.id)&&matchesModel(p)))
const connectedLogins=computed(()=>(state.value.logins||[]).filter(p=>isConnected(p.id)&&matchesModel(p)))
const availableLogins=computed(()=>(state.value.logins||[]).filter(p=>!isConnected(p.id)&&matchesModel(p)))
function configureModel(id){emit('update:open',false);emit('configure-model',({anthropic:'claude',compatible:'custom'})[id]||id)}
const search=ref('')
const tabId = useId()
function navigateTabs(event) {
 const tabs = ['data','models','mcp'], current = tabs.indexOf(tab.value)
 const index = event.key === 'ArrowRight' ? (current + 1) % tabs.length : event.key === 'ArrowLeft' ? (current + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1
 if (index < 0) return
 event.preventDefault(); tab.value = tabs[index]; nextTick(() => document.getElementById(`${tabId}-${tab.value}`)?.focus())
}
const tab=ref('data'),state=ref({}),loading=ref(false),error=ref(''),notice=ref(''),connecting=ref('')
const sources=[
 {name:'Google Analytics',brand:'googleanalytics',icon:ChartNoAxesCombined,color:'#b96a0b',tint:'#fff5e6',description:'Explore traffic, acquisition and conversion data from GA4 exports.'},
 {name:'Google Ads',brand:'googleads',icon:MousePointerClick,color:'#4774ba',tint:'#edf3ff',description:'Compare campaign spend, clicks, conversions and search terms.'},
 {name:'Meta Ads',brand:'meta',icon:Megaphone,color:'#5966bf',tint:'#f0f0ff',description:'Review ad creative, audiences, performance and delivery exports.'},
 {name:'PostHog and product analytics',brand:'posthog',icon:Database,color:'#ab6140',tint:'#fff1e9',description:'Understand product events, funnels and retention from your exports.'},
 {name:'Product documents',icon:FileText,color:'#6c62a1',tint:'#f4f0ff',description:'Add a product brief, research notes or a text document.'},
 {name:'Customer feedback',icon:ContactRound,color:'#3d816a',tint:'#eaf7f0',description:'Ground your decisions in reviews, survey exports and interview notes.'}
]
const filteredSources=computed(()=>sources.filter(c=>`${c.name} ${c.description}`.toLowerCase().includes(search.value.trim().toLowerCase())))
async function load(){loading.value=true;error.value='';try{const results=await Promise.allSettled([api('/api/setup/state'),api('/api/workspace/connectors')]);if(results[0].status==='fulfilled')state.value=results[0].value;else error.value=results[0].reason.message;if(results[1].status==='fulfilled')connectors.value=results[1].value;else error.value=results[1].reason.message}catch(e){error.value=e.message}finally{loading.value=false}}
watch(()=>props.open,open=>{if(open){search.value='';modelSearch.value='';toolSearch.value='';notice.value='';tab.value=['data','models','mcp'].includes(props.initialTab)?props.initialTab:'data';load()}},{immediate:true})
function isConnected(id){return(state.value.gateways||[]).some(g=>g.backend===id&&g.available!==false)}
function hasKey(p){return [p.key_env,...(p.alt_key_envs||[])].some(key=>key&&state.value.keys?.[key])}
function attach(){emit('update:open',false);emit('attach')}
async function connectLogin(login){await connect({kind:'login',backend:login.id,port:login.port,model:login.default_model},login.id)}
async function connect(body,id){connecting.value=id;error.value='';notice.value='';try{await api('/api/setup/provider',{method:'POST',body});notice.value='Connection updated. Your model selector has been refreshed.';await load();emit('connected');window.dispatchEvent(new Event('mm-provider-changed'))}catch(e){error.value=e.message}finally{connecting.value=''}}
</script>
<style scoped>
:global(.connections-dialog){width:min(760px,calc(100vw - 32px));max-width:760px!important;max-height:min(850px,90dvh);overflow:hidden;gap:18px;display:flex!important;flex-direction:column;padding:24px!important}.connections-header,.connections-footer,.connection-tabs{flex-shrink:0}.connections-body{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;padding:0 5px 4px 0}.connections-footer{padding-top:14px;border-top:1px solid var(--line)}.connection-tabs{display:flex;flex-wrap:wrap;gap:6px;padding:4px;border-radius:10px;background:var(--panel-2);width:fit-content}.connection-list{display:flex;flex-direction:column;gap:0}.connection-row{display:flex;gap:14px;align-items:center;padding:18px 0;border-bottom:1px solid var(--line)}.connection-row>div{min-width:0;flex:1}.connection-row b{font-size:13px;font-weight:550}.connection-row p{font-size:12px;line-height:1.7;color:var(--muted);margin-top:5px}.connection-icon{width:36px;height:36px;background:var(--panel-2);border-radius:9px;display:grid;place-items:center;flex-shrink:0}.connection-icon svg{width:18px;height:18px;color:inherit}.connection-method{font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:5px;padding:2px 5px;margin-left:8px;white-space:nowrap}.connection-note{font-size:12px;line-height:1.8;color:var(--muted);margin-top:16px}.connection-error,.connection-notice{font-size:13px;padding:12px;background:var(--panel-2);border-radius:8px;line-height:1.7}.connection-error{color:var(--no)}.api-connections{margin-top:16px}.api-connections summary{cursor:pointer;font-size:13px;font-weight:500}@media(max-width:500px){.connection-row{gap:10px;flex-wrap:wrap}.connection-row>div{min-width:180px}.connection-row>button,.connection-row>a{margin-left:46px}.connection-method{display:none}}
.connection-search{display:flex;align-items:center;gap:9px;min-height:42px;margin-bottom:6px;padding:0 12px;border:1px solid var(--line);border-radius:9px;color:var(--muted)}.connection-search input{width:100%;min-width:0;background:transparent;border:0;outline:none;font:inherit;font-size:13px;color:var(--text)}.connection-search:focus-within{outline:2px solid var(--accent);outline-offset:2px}:global(.connections-dialog[data-theme='dark']) .connection-icon{background:var(--panel-2)!important;color:var(--text)!important}
.mcp-presets{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.mcp-form{display:grid;gap:16px;padding:20px;border:1px solid var(--line);border-radius:14px;margin:4px 0 18px}.mcp-form-title{display:flex;justify-content:space-between;gap:12px;font-size:14px}.mcp-form-title button,.mcp-controls button{border:0;background:transparent;color:var(--muted);font:inherit;font-size:12px;cursor:pointer}.mcp-form label{display:grid;gap:8px;font-size:12px}.mcp-form input,.mcp-form select{width:100%;height:42px;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--text);font:inherit;font-size:13px}.mcp-form>.connection-note{margin:0}.mcp-form>button{justify-self:start;cursor:pointer}.mcp-docs{color:var(--accent);font-size:12px;text-decoration:underline;text-underline-offset:3px}.mcp-controls{display:flex;align-items:center;gap:16px;padding:14px 0}.mcp-controls label{display:flex;gap:9px;align-items:center;flex:1;font-size:12px}.mcp-tools{margin:16px 0}.mcp-tools summary{font-size:12px;cursor:pointer}.mcp-tools>label{display:flex;gap:10px;padding:14px 0;border-bottom:1px solid var(--line)}.mcp-tools input{margin-top:3px;flex-shrink:0}.mcp-tools span{display:grid;gap:6px;min-width:0}.mcp-tools b{font-size:12px;overflow-wrap:anywhere}.mcp-tools small{font-size:12px;line-height:1.7;color:var(--muted);overflow-wrap:anywhere}.mcp-server{border-top:1px solid var(--line);margin-top:14px}.mcp-endpoint{font-size:11px!important;overflow-wrap:anywhere}.mcp-controls input,.mcp-tools input{accent-color:var(--accent)}.mcp-form input:focus-visible,.mcp-form select:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.provider-group{margin:24px 0 8px;font-size:12px;font-weight:600;color:var(--text)}.provider-caption{margin:0 0 8px;font-size:12px;line-height:1.7;color:var(--muted)}.provider-row{padding:12px 0;gap:12px}.provider-row b{font-size:13px}.provider-row p{font-size:12px;margin-top:4px}.provider-row .connection-icon{width:34px;height:34px}.provider-initial{font-size:13px;font-weight:600;color:var(--text)}.provider-connected{font-size:12px;color:var(--muted)}
</style>

<style scoped>
:global(.connections-dialog [data-slot=dialog-title]){font-size:20px;font-weight:600;line-height:1.4;letter-spacing:-.4px}
:global(.connections-dialog [data-slot=dialog-description]){font-size:12px;line-height:1.7;color:var(--muted);margin-top:6px}
.connection-tabs{padding:5px!important;gap:5px!important;border:1px solid var(--line);border-radius:13px!important}
.connection-tabs [role=tab]{padding:9px 14px!important}
@media(max-width:480px){.connection-tabs [role=tab]{padding:9px!important;gap:6px!important}}
</style>
