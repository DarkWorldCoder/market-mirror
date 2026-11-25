<template>
  <div class="mm-clients">
    <div class="mm-conn-section-head">
      <div>
        <h2>Use MarketMirror in your AI apps</h2>
        <p>Add MarketMirror's MCP server to Claude, Cursor or another app, then ask it to test ads, prices or a pitch from there.</p>
      </div>
    </div>
    <LoadingSkeleton v-if="!setup && !error" :lines="3" label="Building the setup for this computer" />
    <p v-else-if="error" class="mm-conn-error" role="alert">{{ error }} <Button variant="outline" size="sm" @click="load">Try again</Button></p>
    <template v-else>
      <p v-if="!setup.server_found" class="mm-conn-error" role="alert">The MCP server file was not found at {{ setup.server_path }}. The setup below will not work until it is there.</p>
      <div class="mm-conn-tabs workspace-modal-tabs" role="tablist" aria-label="AI app" @keydown="keys">
        <button v-for="c in setup.clients" :id="`${uid}-${c.id}`" :key="c.id" type="button" role="tab" :aria-selected="active === c.id" :aria-controls="`${uid}-panel`" :tabindex="active === c.id ? 0 : -1" @click="active = c.id">{{ c.label }}</button>
      </div>
      <section v-if="client" :id="`${uid}-panel`" class="mm-conn-card" role="tabpanel" :aria-labelledby="`${uid}-${client.id}`" tabindex="0">
        <p class="mm-steps"><b>{{ client.format === 'shell' ? 'Run in:' : 'Add to:' }}</b> <code>{{ client.where }}</code><br />{{ client.steps }}</p>
        <figure class="mm-code"><pre :aria-label="`${client.label} setup`"><code>{{ client.snippet }}</code></pre><Button variant="outline" size="sm" @click="copy(client.snippet, client.id)"><Check v-if="copied === client.id" /><Copy v-else />{{ copied === client.id ? 'Copied' : 'Copy' }}</Button></figure>
        <p class="mm-conn-help" style="margin-top:10px">This starts MarketMirror from <code class="mm-path">{{ setup.home }}</code> each time the app needs it. Model calls it makes use the model you set in Settings and ask before spending.</p>
      </section>
      <details class="mm-advanced mm-http">
        <summary><ChevronRight aria-hidden="true" />Connect over HTTP instead</summary>
        <div>
          <p class="mm-conn-help">For apps that take a URL. Make a file holding a long random token (24 characters or more) that only you can read, start the server with it, then give the app the address and token.</p>
          <p class="mm-field" style="margin:0">1. Start the server</p>
          <figure class="mm-code"><pre><code>{{ setup.http.start }}</code></pre><Button variant="outline" size="sm" @click="copy(setup.http.start, 'http-start')"><Check v-if="copied === 'http-start'" /><Copy v-else />{{ copied === 'http-start' ? 'Copied' : 'Copy' }}</Button></figure>
          <p class="mm-field" style="margin:0">2. Add it to your app</p>
          <figure class="mm-code"><pre><code>{{ setup.http.snippet }}</code></pre><Button variant="outline" size="sm" @click="copy(setup.http.snippet, 'http-json')"><Check v-if="copied === 'http-json'" /><Copy v-else />{{ copied === 'http-json' ? 'Copied' : 'Copy' }}</Button></figure>
          <p class="mm-field" style="margin:0">Or, in Claude Code</p>
          <figure class="mm-code"><pre><code>{{ setup.http.claude_code }}</code></pre><Button variant="outline" size="sm" @click="copy(setup.http.claude_code, 'http-cc')"><Check v-if="copied === 'http-cc'" /><Copy v-else />{{ copied === 'http-cc' ? 'Copied' : 'Copy' }}</Button></figure>
          <p class="mm-conn-help">{{ setup.http.note }} Replace the parts in angle brackets with your own file path and token.</p>
        </div>
      </details>
      <p class="ws-sr-only" role="status" aria-live="polite">{{ copied ? 'Copied to the clipboard.' : '' }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, useId } from 'vue'
import { Check, ChevronRight, Copy } from 'lucide-vue-next'
import { Button } from '../ui/button'
import LoadingSkeleton from './LoadingSkeleton.vue'
import { api } from '../../workspace/api.js'

const uid = useId()
const setup = ref(null), error = ref(''), active = ref('claude-desktop'), copied = ref('')
const client = computed(() => setup.value?.clients.find(c => c.id === active.value) || setup.value?.clients[0])
async function load() {
  error.value = ''
  try { setup.value = await api('/api/workspace/mcp-setup') } catch (e) { error.value = e.message }
}
async function copy(text, id) {
  try { await navigator.clipboard.writeText(text) }
  catch {
    const area = document.createElement('textarea'); area.value = text; area.setAttribute('readonly', ''); area.style.position = 'fixed'; area.style.opacity = '0'
    document.body.appendChild(area); area.select(); try { document.execCommand('copy') } finally { area.remove() }
  }
  copied.value = id
  setTimeout(() => { if (copied.value === id) copied.value = '' }, 1800)
}
function keys(event) {
  const ids = setup.value.clients.map(c => c.id), current = ids.indexOf(active.value)
  const next = event.key === 'ArrowRight' ? (current + 1) % ids.length : event.key === 'ArrowLeft' ? (current + ids.length - 1) % ids.length : event.key === 'Home' ? 0 : event.key === 'End' ? ids.length - 1 : -1
  if (next < 0) return
  event.preventDefault(); active.value = ids[next]
  nextTick(() => document.getElementById(`${uid}-${ids[next]}`)?.focus())
}
load()
</script>

<style scoped>
.mm-http { margin-top: 14px; }
.mm-path { font-size: 11.5px; overflow-wrap: anywhere; }
.mm-clients .mm-conn-tabs { margin-bottom: 12px; }
.mm-clients .mm-conn-tabs [role='tab'] { padding: 7px 12px; }
</style>
