<template>
  <!-- Pattern from shadcn.io's onboarding blocks: progress, numbered steps that tick off, one action each. -->
  <Dialog :open="open" @update:open="(v) => { if (!v) emit('update:open', false) }">
    <DialogContent class="ws-overlay mm-onboard gap-5 sm:max-w-xl" :data-theme="theme" @escape-key-down="onEscape">
      <DialogHeader>
        <DialogTitle>Set up {{ state?.workspace.name || 'your workspace' }}</DialogTitle>
        <DialogDescription>A few short steps. Skip any of them; open Setup checklist at the bottom of the sidebar to return.</DialogDescription>
      </DialogHeader>
      <div class="grid gap-2">
        <div class="text-muted-foreground flex justify-between text-xs"><span>{{ doneCount }} of {{ stepList.length }} done</span><span v-if="allDone">All set</span></div>
        <div class="bg-muted h-1.5 overflow-hidden rounded-full" role="progressbar" aria-label="Setup progress" :aria-valuenow="doneCount" :aria-valuetext="`${doneCount} of ${stepList.length} steps done`" aria-valuemin="0" :aria-valuemax="stepList.length"><div class="bg-primary h-full rounded-full transition-all motion-reduce:transition-none" :style="{ width: `${stepList.length ? (doneCount * 100) / stepList.length : 0}%` }"></div></div>
      </div>

      <ol class="grid gap-3">
        <li v-for="(step, index) in stepList" :key="step.id" class="bg-card flex gap-3 rounded-xl border p-4" :class="{ 'opacity-80': isDone(step.id) }">
          <span class="flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium" :class="isDone(step.id) ? 'bg-primary text-primary-foreground border-primary' : 'text-muted-foreground'">
            <Check v-if="isDone(step.id)" class="size-3.5" aria-hidden="true" /><template v-else>{{ index + 1 }}</template>
          </span>
          <div class="grid min-w-0 flex-1 gap-2">
            <p class="text-sm leading-6 font-medium">{{ step.title }}</p>

            <template v-if="step.id === 'workspace'">
              <form v-if="canRename" class="flex gap-2" @submit.prevent="saveName"><Input v-model.trim="name" maxlength="80" aria-label="Workspace name" class="h-8" /><Button size="sm" :disabled="!name || busy">Save</Button></form>
              <p v-else class="text-muted-foreground text-sm">{{ state?.workspace.name }}. Only an owner can rename it.</p>
            </template>

            <template v-else-if="step.id === 'model'">
              <p class="text-muted-foreground text-sm">{{ modelText }}</p>
              <div class="flex flex-wrap gap-2">
                <Button v-if="state?.can_connect_model && !state?.model_connected" size="sm" @click="emit('settings')"><Cpu aria-hidden="true" />Open model settings</Button>
                <Button variant="ghost" size="sm" @click="mark('model')">{{ state?.model_connected ? 'Done' : 'Skip for now' }}</Button>
              </div>
            </template>

            <template v-else-if="step.id === 'invite'">
              <template v-if="state?.can_invite">
                <form class="flex flex-wrap gap-2" @submit.prevent="invite">
                  <Input v-model.trim="email" type="email" placeholder="Email (optional)" aria-label="Teammate email" maxlength="320" class="h-8 min-w-40 flex-1" />
                  <NativeSelect v-model="inviteRole" aria-label="Role" class="h-8 w-28"><option value="editor">{{ roleLabel('editor') }}</option><option value="viewer">{{ roleLabel('viewer') }}</option></NativeSelect>
                  <Button size="sm" :disabled="busy"><Link2 aria-hidden="true" />Create link</Button>
                </form>
                <div v-if="link" class="flex gap-2"><Input :model-value="link" readonly aria-label="Invitation link" class="h-8" @focus="$event.target.select()" /><Button variant="secondary" size="sm" @click="copy"><component :is="copied ? Check : Copy" aria-hidden="true" />{{ copied ? 'Copied' : 'Copy' }}</Button></div>
                <p class="text-muted-foreground text-xs">{{ roleHint(inviteRole) }}</p>
                <p class="text-muted-foreground text-xs">No email is sent; share the link yourself. It works once.</p>
              </template>
              <p v-else-if="state?.mode === 'local'" class="text-muted-foreground text-sm">This app is just for you on this computer. Teams need MarketMirror running on a shared server. Ask whoever set it up, or read the <a class="underline underline-offset-4" href="https://github.com/DarkWorldCoder/market-mirror/blob/main/docs/ACCOUNTS.md" target="_blank" rel="noopener noreferrer">team guide</a>.</p>
              <p v-else class="text-muted-foreground text-sm">Ask an owner of this workspace to invite people.</p>
              <div><Button variant="ghost" size="sm" @click="mark('invite')">{{ link ? 'Done' : 'Skip' }}</Button></div>
            </template>

            <template v-else>
              <p class="text-muted-foreground text-sm">A finished test with its simulated buyers, report and decision. It needs no model and spends nothing. Every number in it is simulated.</p>
              <div class="flex flex-wrap gap-2">
                <Button as="a" size="sm" variant="outline" :href="state?.demo_url" target="_blank" rel="noopener noreferrer" @click="mark('demo')"><ArrowUpRight aria-hidden="true" />Open the demo</Button>
                <Button v-if="latestRun" variant="ghost" size="sm" @click="openLatest">Open your latest run</Button>
              </div>
            </template>
          </div>
        </li>
      </ol>
      <p v-if="error" class="text-destructive text-sm" role="alert">{{ error }}</p>
      <DialogFooter><Button @click="finish">{{ allDone ? 'Finish' : 'Close setup' }}</Button></DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowUpRight, Check, Copy, Cpu, Link2 } from 'lucide-vue-next'
import { Button } from '../ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../ui/dialog'
import { Input } from '../ui/input'
import { NativeSelect } from '../ui/native-select'
import { roleHint, roleLabel } from '../../workspace/roles.js'
import { api } from '../../workspace/api.js'
import { canEdit, isOwner } from '../../workspace/account.js'

const props = defineProps({ open: Boolean, theme: { type: String, default: 'light' }, latestRun: { type: String, default: '' } })
const emit = defineEmits(['update:open', 'settings'])
const router = useRouter()
const state = ref(null), error = ref(''), busy = ref(false)
const name = ref(''), email = ref(''), inviteRole = ref('editor'), link = ref(''), copied = ref(false)
// Only show steps the person can actually do: renaming needs an owner, inviting
// needs an owner too, and a viewer can only dismiss the checklist.
const stepList = computed(() => [
  ...(isOwner.value ? [{ id: 'workspace', title: 'Name your workspace' }] : []),
  { id: 'model', title: 'Connect a model' },
  ...(state.value?.can_invite ? [{ id: 'invite', title: 'Invite teammates' }] : []),
  { id: 'demo', title: 'Try the saved demo' }
])
const steps = computed(() => state.value?.steps || {})
const isDone = (id) => !!steps.value[id] || (id === 'model' && !!state.value?.model_connected)
const doneCount = computed(() => stepList.value.filter(s => isDone(s.id)).length)
const allDone = computed(() => doneCount.value === stepList.value.length)
const canRename = computed(() => isOwner.value)
const modelText = computed(() => state.value?.model_connected
  ? 'A model is connected. Simulated buyers answer through it, and you approve any spending before a run.'
  : state.value?.can_connect_model
    ? 'No model yet. Add an API key or a local login in Settings. The saved demo works without one.'
    : 'No model yet. Whoever runs MarketMirror on the server connects one there with ./mm setup.')

async function load() {
  try { state.value = await api('/api/workspace/onboarding'); name.value = state.value.workspace.name } catch (err) { error.value = err.message }
}
async function mark(step, value = true) {
  if (!canEdit.value && step !== 'dismissed') return
  try { state.value = await api('/api/workspace/onboarding', { method: 'PUT', body: { steps: { [step]: value } } }) }
  catch (err) { error.value = err.message }
}
async function saveName() {
  busy.value = true; error.value = ''
  try { await api('/api/team/workspace', { method: 'PATCH', body: { name: name.value } }); await mark('workspace'); window.dispatchEvent(new Event('mm-workspace-renamed')) }
  catch (err) { error.value = err.message } finally { busy.value = false }
}
async function invite() {
  busy.value = true; error.value = ''
  try { link.value = (await api('/api/team/invitations', { method: 'POST', body: { email: email.value || null, role: inviteRole.value } })).url; copied.value = false; email.value = '' }
  catch (err) { error.value = err.message } finally { busy.value = false }
}
async function copy() { try { await navigator.clipboard.writeText(link.value); copied.value = true } catch { error.value = 'Select the link and copy it by hand.' } }
async function openLatest() { await mark('demo'); finish(); router.push({ path: '/', query: { run: props.latestRun, show: 'reports' } }) }
function onEscape(event) { event.preventDefault(); emit('update:open', false) }
async function finish() { if (state.value && !steps.value.dismissed) await mark('dismissed'); emit('update:open', false) }

watch(() => props.open, (value) => { if (value) load() }, { immediate: true })
</script>

<style>
.ws-overlay.mm-onboard p, .ws-overlay.mm-onboard ol { margin: 0; padding: 0; list-style: none; }
.ws-overlay.mm-onboard code { font-size: 12px; }
@layer base { .mm-onboard *, .mm-onboard *::before, .mm-onboard *::after { border-color: var(--line); } }
</style>
