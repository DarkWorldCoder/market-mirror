<script setup>
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { Globe, LoaderCircle, Camera, FileText, Maximize2, Copy, Check, MessageSquare } from 'lucide-vue-next'
import { ensureSession, token } from '../../workspace/api'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog'
import InfoHint from './InfoHint.vue'
const props = defineProps({ observation: { type: Object, required: true }, theme: { type: String, default: 'light' }, canAsk: Boolean })
const emit = defineEmits(['ask'])
const selected = ref(0), view = ref('screenshot'), image = ref(''), loading = ref(false), error = ref(''), expanded = ref(false), copied = ref(false), copyError = ref(''), id = useId()
const tabs = [{id:'screenshot',label:'Screenshot',icon:Camera},{id:'text',label:'Parsed text',icon:FileText}]
let version = 0
const frames = computed(() => Array.isArray(props.observation.screenshots) && props.observation.screenshots.length ? props.observation.screenshots.filter(item=>item&&typeof item.url==='string') : [{ label: 'Page snapshot', url: props.observation.screenshot }])
const frame = computed(() => frames.value[selected.value] || frames.value[0])
function safeUrl(value) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : '' } catch { return '' } }
const source = computed(() => safeUrl(props.observation.url))
const text = computed(() => typeof props.observation.text === 'string' ? props.observation.text : '')
const characterCount = computed(() => new Intl.NumberFormat().format(Array.from(text.value).length))
const links = computed(() => (Array.isArray(props.observation.links) ? props.observation.links : []).map(link => ({text:typeof link?.text==='string'?link.text:'',url:safeUrl(link?.url)})).filter(link=>link.url))
const capturedAt = computed(() => { const value=props.observation.created_at;if(!value)return '';const date=new Date(typeof value==='number'?value*1000:value);return Number.isFinite(date.getTime())?date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'' })
function clear(){if(image.value)URL.revokeObjectURL(image.value);image.value=''}
async function loadImage(path = frame.value?.url) {
 const current = ++version; clear(); error.value = ''; loading.value = false
 // Only the existing authenticated local screenshot route may supply image bytes.
 if(!/^\/api\/workspace\/browser\/br_[a-f0-9]{24}\/image(?:\?frame=[01])?$/.test(path || '')){error.value='Screenshot is unavailable.';return}
 loading.value=true
 try{await ensureSession();const response=await fetch(path,{credentials:'same-origin',headers:{'X-Setup-Token':token()},cache:'no-store'});if(!response.ok||!response.headers.get('content-type')?.includes('image/png'))throw new Error('Screenshot expired or could not be loaded.');const blob=await response.blob();if(current===version)image.value=URL.createObjectURL(blob)}catch(err){if(current===version)error.value=err.message}finally{if(current===version)loading.value=false}
}
watch(() => frame.value?.url, path=>loadImage(path), {immediate:true})
watch(() => props.observation, () => { selected.value=0;copied.value=false;copyError.value='' })
function tabKey(event) {if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();view.value=event.key==='Home'?'screenshot':event.key==='End'?'text':view.value==='screenshot'?'text':'screenshot';document.getElementById(`${id}-${view.value}`)?.focus()}
async function copyLink(){try{await navigator.clipboard.writeText(source.value);copied.value=true;copyError.value=''}catch{copyError.value='Select the source link to copy it.'}}
onBeforeUnmount(()=>{version++;clear()})
</script>
<template>
 <section class="browser-observation" aria-label="Captured web page">
  <header><Globe :size="17" /><div><strong>{{ observation.title || 'Observed page' }}</strong><a v-if="source" :href="source" target="_blank" rel="noopener noreferrer" :title="source">{{ source }}</a></div><button v-if="source" class="browser-icon-action" :aria-label="copied?'Page link copied':'Copy page link'" :title="copied?'Copied':'Copy page link'" @click="copyLink"><Check v-if="copied" :size="15" /><Copy v-else :size="15" /></button></header>
  <div class="browser-capture-meta"><span v-if="capturedAt">Captured {{ capturedAt }}</span><span v-if="observation.status_code">HTTP {{ observation.status_code }}</span><InfoHint :theme="theme" label="About this page capture">This is a saved, read-only browser snapshot. JavaScript was disabled, so interactive or client-rendered content may be missing. The preview does not load the live website.</InfoHint></div>
  <p v-if="copyError" class="browser-copy-error" role="status">{{ copyError }}</p>
  <div class="browser-content-tabs workspace-modal-tabs" role="tablist" aria-label="Web page preview" @keydown="tabKey"><button v-for="tab in tabs" :id="`${id}-${tab.id}`" :key="tab.id" role="tab" :tabindex="view===tab.id?0:-1" :aria-selected="view===tab.id" :aria-controls="`${id}-panel`" @click="view=tab.id"><component :is="tab.icon" :size="14" />{{ tab.label }}</button></div>
  <div :id="`${id}-panel`" class="browser-content-panel" role="tabpanel" :aria-labelledby="`${id}-${view}`" tabindex="0">
   <template v-if="view==='screenshot'"><div class="browser-frame-toolbar"><div v-if="frames.length>1" class="browser-frames" role="group" aria-label="Captured page sections"><button v-for="(item,index) in frames" :key="item.url" type="button" :aria-pressed="selected===index" @click="selected=index">{{ item.label }}</button></div><button class="browser-expand" :disabled="!image" @click="expanded=true"><Maximize2 :size="13" />Expand</button></div><div class="browser-image"><div v-if="loading" class="browser-loading" role="status"><LoaderCircle :size="18" />Loading screenshot…</div><button v-else-if="image" class="browser-image-button" :aria-label="`Expand ${frame?.label || 'page'} screenshot`" @click="expanded=true"><img :src="image" :alt="`${frame?.label || 'Page snapshot'}: ${observation.title || 'observed page'}`" /></button><div v-else class="browser-image-error"><p role="alert">{{ error }}</p><button type="button" @click="loadImage()">Retry screenshot</button></div></div></template>
   <div v-else class="browser-parsed"><div class="browser-text-heading"><strong>Extracted page text</strong><span>{{ characterCount }} saved characters</span></div><p v-if="observation.text_truncated" class="browser-excerpt-note">The capture contains a bounded excerpt of the page text.</p><pre v-if="text">{{ text }}</pre><p v-else class="browser-text-empty">No rendered page text was saved in this capture.</p><details v-if="links.length" class="browser-links"><summary>Links found on the page ({{ links.length }})</summary><ul><li v-for="(link,index) in links" :key="index"><a :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.text || link.url }}<small v-if="link.text">{{ link.url }}</small></a></li></ul></details></div>
  </div>
  <details class="browser-events"><summary>Capture activity</summary><ol><li v-for="(event,index) in observation.events || []" :key="index">{{ event.detail }}</li></ol><p v-if="!observation.events?.length">No capture activity was saved.</p></details>
  <footer v-if="canAsk && text.trim() && source" class="browser-question">
   <button type="button" @click="emit('ask')"><MessageSquare :size="14" aria-hidden="true" />Ask about this page</button>
  </footer>
  <Dialog v-model:open="expanded"><DialogContent class="ws-overlay browser-snapshot-dialog" :data-theme="theme"><DialogHeader><DialogTitle>{{ observation.title || 'Captured web page' }}</DialogTitle><DialogDescription>{{ frame?.label || 'Page snapshot' }} · Saved screenshot. The live website is not loaded here.</DialogDescription></DialogHeader><div class="browser-snapshot-full"><img v-if="image" :src="image" :alt="`${frame?.label || 'Page snapshot'}: ${observation.title || 'observed page'}`" /><p v-else>{{ error || 'Screenshot is unavailable.' }}</p></div></DialogContent></Dialog>
 </section>
</template>
<style>
.browser-observation{border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--panel);margin:16px 0;min-width:0}.browser-observation>header{display:flex;align-items:center;gap:11px;padding:16px 17px 9px}.browser-observation>header>svg{flex-shrink:0;color:var(--muted)}.browser-observation>header>div{display:grid;gap:5px;min-width:0;flex:1}.browser-observation strong{font-size:13px;font-weight:550;line-height:1.6}.browser-observation header a{font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.browser-icon-action{display:grid;place-items:center;width:29px;height:29px;border:0;border-radius:7px;background:transparent;color:var(--muted);cursor:pointer;flex-shrink:0}.browser-icon-action:hover{background:var(--panel-2);color:var(--text)}.browser-capture-meta{display:flex;align-items:center;gap:12px;padding:0 17px 13px 45px;color:var(--muted);font-size:10px;flex-wrap:wrap}.browser-capture-meta .settings-info-trigger{width:21px;height:21px;padding:2px}.browser-content-tabs{display:flex;align-items:center;gap:5px;padding:7px 12px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--panel-2)}.browser-content-tabs>button{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:8px 12px;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--muted);font:inherit;font-size:11px;cursor:pointer}.browser-content-tabs>button[aria-selected=true]{background:var(--panel);border-color:var(--line);color:var(--text);box-shadow:inset 0 -2px 0 var(--accent),0 1px 3px #24253608}.browser-content-panel{min-width:0}.browser-frame-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 14px}.browser-frames{display:flex;flex-wrap:wrap;gap:5px}.browser-frames button{padding:6px 8px;border:1px solid transparent;border-radius:7px;background:transparent;color:var(--muted);font:inherit;font-size:10px;cursor:pointer}.browser-frames button[aria-pressed=true]{border-color:var(--line);background:var(--panel);color:var(--text)}.browser-expand{display:flex;align-items:center;gap:6px;margin-left:auto;padding:6px 8px;border:0;border-radius:7px;background:transparent;color:var(--muted);font:inherit;font-size:10px;cursor:pointer;white-space:nowrap}.browser-expand:disabled{opacity:.45;cursor:default}.browser-image{min-height:160px;background:var(--panel-2);overflow:auto;max-height:480px}.browser-image-button{display:block;width:100%;padding:0;border:0;background:transparent;cursor:zoom-in}.browser-image img{display:block;width:100%;height:auto}.browser-loading,.browser-image-error{padding:32px;font-size:12px;color:var(--muted);display:flex;gap:10px;align-items:center;justify-content:center;min-height:160px}.browser-loading>svg{animation:browser-image-loading 1s linear infinite}.browser-image-error{flex-direction:column;line-height:1.7}.browser-image-error button{padding:7px 11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);font:inherit;font-size:11px;cursor:pointer}.browser-parsed{padding:17px}.browser-text-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:13px}.browser-text-heading>strong{font-size:12px}.browser-text-heading>span{font-size:10px;color:var(--muted);white-space:nowrap}.browser-parsed pre{max-height:420px;overflow:auto;margin:0;font:inherit;font-size:12px;line-height:1.85;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--text)}.browser-excerpt-note,.browser-text-empty,.browser-copy-error{font-size:11px;line-height:1.7;color:var(--muted);margin:0 0 12px}.browser-copy-error{padding:0 17px}.browser-links{margin-top:17px;padding-top:14px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}.browser-links summary{cursor:pointer}.browser-links ul{list-style:none;padding:0;margin:10px 0 0}.browser-links li{padding:8px 0}.browser-links a{display:block;color:var(--text);text-decoration:underline;overflow-wrap:anywhere}.browser-links small{display:block;color:var(--muted);font-size:10px;line-height:1.6;margin-top:4px}.browser-events{padding:13px 17px;color:var(--muted);font-size:10px;line-height:1.8;border-top:1px solid var(--line)}.browser-events summary{cursor:pointer;font-size:11px}.browser-events ol{padding-left:18px;margin:10px 0 0}.browser-events p{margin:8px 0 0}.browser-snapshot-dialog{width:min(1200px,calc(100vw - 32px))!important;max-width:1200px!important;max-height:92dvh;overflow:auto;padding:23px!important;border-radius:20px!important;background:var(--panel)!important;border-color:var(--line)!important;color:var(--text)!important}.browser-snapshot-dialog [data-slot=dialog-title]{max-width:calc(100% - 25px);font-size:16px;line-height:1.6}.browser-snapshot-dialog [data-slot=dialog-description]{font-size:11px;color:var(--muted);line-height:1.7}.browser-snapshot-full{min-width:0;overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--panel-2)}.browser-snapshot-full img{display:block;width:100%;height:auto}.browser-snapshot-full p{padding:30px;font-size:12px;color:var(--muted)}.browser-observation :focus-visible{outline:2px solid var(--accent);outline-offset:2px}@keyframes browser-image-loading{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.browser-loading>svg{animation:none}}@media(max-width:480px){.browser-observation>header{padding:14px 13px 8px}.browser-capture-meta{padding-left:41px;font-size:9px;gap:9px}.browser-parsed{padding:14px}.browser-text-heading{align-items:flex-start;flex-direction:column;gap:4px}.browser-snapshot-dialog{padding:18px!important}}
</style>
<style scoped>
.browser-question {
  display: flex;
  padding: 8px 12px;
  border-top: 1px solid var(--line);
}
.browser-question button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 9px;
  border-radius: 7px;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
}
.browser-question button:hover { background: var(--panel-2); }
</style>
