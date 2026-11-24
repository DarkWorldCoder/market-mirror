<template>
  <div class="mm-mcp">
    <div class="mm-conn-section-head">
      <div>
        <h2>{{ heading }}</h2>
        <p>Add a remote MCP server, check its tools, then choose which read-only tools chat may use.</p>
      </div>
      <Button size="sm" @click="openAdd()"><Plus />Add MCP server</Button>
    </div>
    <p v-if="error" class="mm-conn-error" role="alert">{{ error }}</p>
    <p class="ws-sr-only" role="status" aria-live="polite">{{ announce }}</p>
    <LoadingSkeleton v-if="loading && !connectors.length" :lines="3" label="Loading your MCP servers" />
    <div v-else-if="!connectors.length" class="mm-empty">
      <Plug aria-hidden="true" />
      <b>No MCP servers yet</b>
      Add one by pasting its https address. Meta Ads and Google Analytics have quick presets.
    </div>
    <div v-else class="mm-conn-list">
      <article v-for="c in connectors" :key="c.id" class="mm-conn-card" :aria-labelledby="`mcp-${c.id}-name`">
        <div class="mm-conn-card-top">
          <span class="mm-conn-icon"><BrandIcon v-if="brandOf(c)" :brand="brandOf(c)" :size="20" /><Plug v-else aria-hidden="true" /></span>
          <div class="mm-conn-body">
            <div class="mm-conn-title"><h3 :id="`mcp-${c.id}-name`">{{ c.name }}</h3><span class="mm-badge" :class="connectorStatus(c).tone">{{ connectorStatus(c).label }}</span></div>
            <p class="mm-conn-meta">{{ transportLabel() }} · {{ c.checked_at ? `checked ${relativeTime(c.checked_at)}` : 'never checked' }}<template v-if="c.status === 'connected'"> · {{ c.tools.length }} {{ c.tools.length === 1 ? 'tool' : 'tools' }}, {{ allowedCount(c) }} on in chat</template></p>
            <p class="mm-conn-meta mm-mono">{{ c.url }}</p>
            <p v-if="c.error && c.status !== 'connected'" class="mm-conn-error">{{ c.error }}</p>
          </div>
        </div>
        <div class="mm-conn-actions">
          <button type="button" class="mm-switch" role="switch" :aria-checked="c.enabled" :disabled="busy === c.id" @click="patch(c, { enabled: !c.enabled })"><span aria-hidden="true"></span>Use in chat</button>
          <span class="spacer"></span>
          <Button variant="outline" size="sm" :disabled="!!busy" @click="discover(c)"><LoaderCircle v-if="busy === `check:${c.id}`" class="mm-spin" />{{ busy === `check:${c.id}` ? 'Testing…' : 'Test' }}</Button>
          <Button variant="ghost" size="sm" @click="openEdit(c)"><Pencil />Edit</Button>
          <Button v-if="confirming !== c.id" variant="ghost" size="sm" @click="confirming = c.id"><Trash2 />Remove</Button>
          <span v-else class="mm-confirm" role="group" :aria-label="`Remove ${c.name}?`"><span>Remove?</span><Button variant="destructive" size="sm" @click="remove(c)">Remove</Button><Button variant="ghost" size="sm" @click="confirming = ''">Keep</Button></span>
          <Button v-if="c.tools.length" variant="ghost" size="sm" :aria-expanded="open.includes(c.id)" :aria-controls="`mcp-${c.id}-tools`" @click="toggleOpen(c.id)"><ChevronDown :class="{ 'mm-rot': open.includes(c.id) }" />Tools ({{ c.tools.length }})</Button>
        </div>
        <div v-if="open.includes(c.id) && c.tools.length" :id="`mcp-${c.id}-tools`" class="mm-tools">
          <input v-if="c.tools.length > 6" v-model="toolSearch[c.id]" type="search" :aria-label="`Search tools in ${c.name}`" placeholder="Search tools" />
          <div v-for="tool in visibleTools(c)" :key="tool.name" class="mm-tool">
            <button type="button" class="mm-switch" role="switch" :aria-checked="c.allowed_tools.includes(tool.name)" :aria-label="`Allow ${tool.name} in chat`" :disabled="!toolHint(tool).usable || busy === c.id" @click="toggleTool(c, tool.name)"><span aria-hidden="true"></span></button>
            <div><b>{{ tool.name }}</b><small v-if="tool.description">{{ tool.description }}</small><span class="mm-badge" :class="toolHint(tool).usable ? 'ok' : 'idle'">{{ toolHint(tool).label }}</span><small v-if="!toolHint(tool).usable">Chat can only use tools the server marks read-only.</small></div>
          </div>
          <p v-if="!visibleTools(c).length" class="mm-conn-help">No tools match.</p>
          <p v-if="c.tools_truncated" class="mm-conn-help">This server has more tools than we list. Only the ones shown can be used.</p>
        </div>
      </article>
    </div>

    <Dialog :open="dialogOpen" @update:open="dialogOpen = $event">
      <DialogContent class="ws-overlay mm-mcp-dialog" :data-theme="theme">
        <DialogHeader><DialogTitle>{{ editing ? `Edit ${draft.name || 'server'}` : 'Add MCP server' }}</DialogTitle><DialogDescription>Paste the server's https address. Check it, then save.</DialogDescription></DialogHeader>
        <form class="mm-form" novalidate @submit.prevent="save">
          <div v-if="!editing" class="mm-presets" role="group" aria-label="Quick presets"><span>Quick start:</span><Button type="button" variant="outline" size="sm" @click="preset('Meta Ads')"><BrandIcon brand="meta" :size="15" />Meta Ads</Button><Button type="button" variant="outline" size="sm" @click="preset('Google Analytics')"><BrandIcon brand="googleanalytics" :size="15" />Google Analytics</Button></div>
          <p v-if="presetNote" class="mm-note" style="margin:0">{{ presetNote }} <a v-if="presetDocs" :href="presetDocs" target="_blank" rel="noopener noreferrer">Setup guide<span class="ws-sr-only"> (opens in a new tab)</span> ↗</a></p>
          <label class="mm-field">Name<input v-model="draft.name" class="mm-input" maxlength="100" autocomplete="off" placeholder="For example: Ads account" :aria-invalid="!!shownErrors.name" aria-describedby="mcp-name-err" @blur="touched.name = true" /><small v-if="shownErrors.name" id="mcp-name-err" class="err">{{ shownErrors.name }}</small></label>
          <label class="mm-field">Server address<input v-model="draft.url" class="mm-input" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://your-server.example/mcp" :aria-invalid="!!shownErrors.url" aria-describedby="mcp-url-help" @blur="touched.url = true" /><small v-if="shownErrors.url" id="mcp-url-help" class="err">{{ shownErrors.url }}</small><small v-else id="mcp-url-help">A public https address that speaks Streamable HTTP. Servers that only run on your computer (stdio) cannot be added here.</small></label>
          <div class="mm-field"><label for="mcp-token">Access token <small>(optional)</small></label><div class="mm-secret"><input id="mcp-token" v-model="draft.token" class="mm-input" :type="showToken ? 'text' : 'password'" autocomplete="new-password" spellcheck="false" :placeholder="editing && savedToken ? 'Saved. Leave blank to keep it' : 'Only if the server asks for one'" aria-describedby="mcp-token-help" /><Button type="button" variant="outline" size="sm" :aria-pressed="showToken" :aria-label="showToken ? 'Hide token' : 'Show token'" @click="showToken = !showToken"><EyeOff v-if="showToken" /><Eye v-else /></Button></div><small id="mcp-token-help">Sent as a bearer token. It stays on this computer and is never shown again. Custom headers and sign-in pages (OAuth) are not supported.</small><label v-if="editing && savedToken" class="mm-check"><input v-model="clearToken" type="checkbox" />Remove the saved token</label></div>
          <details class="mm-advanced"><summary><ChevronRight aria-hidden="true" />Advanced</summary><div><label class="mm-field">Protocol version<select v-model="draft.protocol_version" class="mm-input"><option value="2025-11-25">2025-11-25 (newest)</option><option value="2025-06-18">2025-06-18</option></select><small>Change this only if the server says it needs the older version.</small></label></div></details>
          <div class="mm-test" aria-live="polite">
            <p v-if="test?.status === 'connected'" class="mm-conn-ok"><CheckCircle2 :size="14" /> Connected. {{ test.tools.length }} {{ test.tools.length === 1 ? 'tool' : 'tools' }} found, {{ test.tools.filter(t => t.read_only).length }} read-only.</p>
            <p v-else-if="test" class="mm-conn-error">{{ test.error || 'The server did not answer.' }}</p>
          </div>
          <p v-if="dialogError" class="mm-conn-error" role="alert">{{ dialogError }}</p>
          <DialogFooter class="mm-dialog-actions">
            <Button type="button" variant="outline" :disabled="!!busy" @click="runTest"><LoaderCircle v-if="busy === 'test'" class="mm-spin" />{{ busy === 'test' ? 'Checking…' : test ? 'Check again' : 'Test connection' }}</Button>
            <Button type="submit" :disabled="!!busy || !test"><LoaderCircle v-if="busy === 'save'" class="mm-spin" />{{ !test ? 'Save (test first)' : test.status === 'connected' ? 'Save server' : 'Save anyway' }}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { CheckCircle2, ChevronDown, ChevronRight, Eye, EyeOff, LoaderCircle, Pencil, Plug, Plus, Trash2 } from 'lucide-vue-next'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../ui/dialog'
import BrandIcon from '../BrandIcon.vue'
import LoadingSkeleton from './LoadingSkeleton.vue'
import { api } from '../../workspace/api.js'
import { connectorStatus, relativeTime, toolHint, transportLabel, validateServerDraft } from '../../workspace/connections.js'

defineProps({ theme: { type: String, default: 'light' }, heading: { type: String, default: 'Your MCP servers' } })
const emit = defineEmits(['changed'])
const connectors = ref([]), loading = ref(false), error = ref(''), announce = ref(''), busy = ref(''), confirming = ref('')
const open = ref([]), toolSearch = reactive({})
const dialogOpen = ref(false), editing = ref(''), savedToken = ref(false), clearToken = ref(false), showToken = ref(false)
const draft = ref(blank()), touched = reactive({ name: false, url: false }), submitted = ref(false)
const test = ref(null), dialogError = ref(''), presetNote = ref(''), presetDocs = ref('')

function blank() { return { name: '', url: '', token: '', protocol_version: '2025-11-25' } }
const errors = computed(() => validateServerDraft(draft.value))
const shownErrors = computed(() => ({ name: (touched.name || submitted.value) ? errors.value.name : '', url: (touched.url || submitted.value) ? errors.value.url : '' }))
watch(() => [draft.value.url, draft.value.token, draft.value.protocol_version], () => { test.value = null })

function brandOf(c) { return c.url.startsWith('https://mcp.facebook.com/') ? 'meta' : /analytics/i.test(c.name) ? 'googleanalytics' : '' }
function allowedCount(c) { return c.tools.filter(t => t.read_only && c.allowed_tools.includes(t.name)).length }
function visibleTools(c) { const q = String(toolSearch[c.id] || '').trim().toLowerCase(); return c.tools.filter(t => `${t.name} ${t.description}`.toLowerCase().includes(q)) }
function toggleOpen(id) { open.value = open.value.includes(id) ? open.value.filter(x => x !== id) : [...open.value, id] }

async function load() {
  loading.value = true
  try { connectors.value = await api('/api/workspace/connectors'); error.value = '' }
  catch (e) { error.value = e.message }
  finally { loading.value = false }
}
async function patch(c, body) {
  busy.value = c.id; error.value = ''
  try { await api(`/api/workspace/connectors/${c.id}`, { method: 'PATCH', body }); await load(); announce.value = 'enabled' in body ? `${c.name} ${body.enabled ? 'is on' : 'is off'} in chat.` : 'Tool choice saved.'; emit('changed') }
  catch (e) { error.value = e.message; await load().catch(() => {}) }
  finally { busy.value = '' }
}
function toggleTool(c, name) { const on = !c.allowed_tools.includes(name); patch(c, { allowed_tools: on ? [...c.allowed_tools, name] : c.allowed_tools.filter(t => t !== name) }) }
async function discover(c) {
  busy.value = `check:${c.id}`; error.value = ''
  try {
    const result = await api(`/api/workspace/connectors/${c.id}/discover`, { method: 'POST', body: {} })
    await load()
    announce.value = result.status === 'connected' ? `${c.name} connected. ${result.tools.length} tools found.` : `${c.name} could not connect.`
    if (result.status === 'connected' && !open.value.includes(c.id)) open.value = [...open.value, c.id]
    emit('changed')
  } catch (e) { error.value = e.message }
  finally { busy.value = '' }
}
async function remove(c) {
  confirming.value = ''; error.value = ''
  try { await api(`/api/workspace/connectors/${c.id}`, { method: 'DELETE' }); await load(); announce.value = `${c.name} removed.`; emit('changed') }
  catch (e) { error.value = e.message }
}

function reset() { Object.assign(touched, { name: false, url: false }); submitted.value = false; test.value = null; dialogError.value = ''; showToken.value = false; clearToken.value = false; presetNote.value = ''; presetDocs.value = '' }
function openAdd(name = '') { reset(); editing.value = ''; savedToken.value = false; draft.value = blank(); if (name) preset(name); dialogOpen.value = true }
function openEdit(c) { reset(); editing.value = c.id; savedToken.value = !!c.token_configured; draft.value = { name: c.name, url: c.url, token: '', protocol_version: c.protocol_version || '2025-11-25' }; dialogOpen.value = true }
function preset(name) {
  draft.value = { ...blank(), name, url: name === 'Meta Ads' ? 'https://mcp.facebook.com/ads' : '' }
  presetNote.value = name === 'Meta Ads'
    ? 'Needs a Meta access token with ads_read permission (from a user or a system user). Sign-in pages are not supported.'
    : 'Google publishes an open-source Analytics MCP server. Run it behind a public https address and paste that address here.'
  presetDocs.value = name === 'Meta Ads' ? 'https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-get-started' : 'https://developers.google.com/analytics/devguides/MCP'
}
async function runTest() {
  submitted.value = true; dialogError.value = ''
  if (errors.value.url) return
  busy.value = 'test'
  try {
    const body = { url: draft.value.url.trim(), protocol_version: draft.value.protocol_version, ...(draft.value.token && !clearToken.value ? { token: draft.value.token } : {}) }
    const query = editing.value && !clearToken.value ? `?connector=${encodeURIComponent(editing.value)}` : ''
    test.value = await api(`/api/workspace/connectors/test${query}`, { method: 'POST', body })
  } catch (e) { dialogError.value = e.message }
  finally { busy.value = '' }
}
async function save() {
  submitted.value = true; dialogError.value = ''
  if (Object.keys(errors.value).length || !test.value) return
  busy.value = 'save'
  try {
    const body = { name: draft.value.name.trim(), url: draft.value.url.trim(), protocol_version: draft.value.protocol_version, ...(draft.value.token ? { token: draft.value.token } : {}), ...(clearToken.value ? { clear_token: true } : {}) }
    const saved = await api('/api/workspace/connectors' + (editing.value ? `/${editing.value}` : ''), { method: editing.value ? 'PATCH' : 'POST', body })
    const passed = test.value?.status === 'connected'
    draft.value.token = ''
    dialogOpen.value = false
    if (passed) await discover(saved)
    else await load()
    announce.value = `${saved.name} saved.`
    emit('changed')
  } catch (e) { dialogError.value = e.message }
  finally { if (busy.value === 'save') busy.value = '' }
}
load()
defineExpose({ openAdd, load, connectors })
</script>

<style scoped>
.mm-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px !important; }
.mm-confirm { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--no); }
.mm-rot { transform: rotate(180deg); }
.mm-spin { animation: mm-spin 1s linear infinite; }
@keyframes mm-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .mm-spin { animation: none; } }
:global(.mm-mcp-dialog) { width: min(560px, calc(100vw - 24px)); max-width: 560px !important; max-height: 90dvh; overflow-y: auto; padding: 24px !important; border-radius: 18px !important; }
:global(.mm-mcp-dialog [data-slot=dialog-title]) { font-size: 18px; font-weight: 600; letter-spacing: -.3px; }
:global(.mm-mcp-dialog [data-slot=dialog-description]) { font-size: 12.5px; color: var(--muted); }
.mm-presets { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12.5px; color: var(--muted); }
.mm-note a { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.mm-check { display: flex; align-items: center; gap: 8px; font-weight: 400; font-size: 12.5px; color: var(--muted); }
.mm-check input { accent-color: var(--accent); width: 16px; height: 16px; }
.mm-test:empty { display: none; }
.mm-test p { display: flex; align-items: center; gap: 6px; margin: 0; }
.mm-dialog-actions { gap: 8px; padding-top: 4px; }
@media (max-width: 480px) { .mm-dialog-actions { flex-direction: column-reverse; } .mm-dialog-actions > * { width: 100%; } }
</style>
