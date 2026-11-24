<template>
  <!-- Blocks: shadcn.io "account team members" (rows with avatar, role and pending invitations) and the
       ui.shadcn.com cards example "Share this document" (link with Copy, people with access). -->
  <div class="ws-section mm-team mx-auto grid w-full max-w-3xl gap-6" style="padding-top: 24px">
    <div class="grid gap-1">
      <h1 class="text-2xl font-semibold tracking-tight">Workspace and team</h1>
      <p class="text-muted-foreground text-sm">{{ intro }}</p>
    </div>
    <p v-if="error" class="text-destructive border-destructive/30 bg-destructive/5 rounded-lg border px-3 py-2 text-sm" role="alert">{{ error }}</p>

    <Card>
      <CardHeader>
        <CardTitle>Workspace</CardTitle>
        <CardDescription>{{ isOwner ? 'The name your teammates see.' : `You are ${roleText(role)} here.` }}</CardDescription>
        <CardAction v-if="data"><Badge variant="secondary">{{ role }}</Badge></CardAction>
      </CardHeader>
      <CardContent class="grid gap-4">
        <form v-if="isOwner" class="flex flex-wrap items-end gap-3" @submit.prevent="rename">
          <div class="grid min-w-48 flex-1 gap-2"><Label for="mm-ws-name">Name</Label><Input id="mm-ws-name" v-model.trim="workspaceName" maxlength="80" required /></div>
          <Button variant="outline" :disabled="busy || !workspaceName || workspaceName === data?.workspace.name">Rename</Button>
        </form>
        <p v-else class="text-sm font-medium">{{ data?.workspace.name }}</p>
        <template v-if="signedIn">
          <div v-if="account.workspaces.length > 1" class="grid gap-2">
            <Label for="mm-ws-switch">Switch workspace</Label>
            <NativeSelect id="mm-ws-switch" :model-value="account.workspace?.id" class="w-full" @update:model-value="switchTo"><option v-for="w in account.workspaces" :key="w.id" :value="w.id">{{ w.name }} · {{ w.role }}</option></NativeSelect>
          </div>
          <form class="flex flex-wrap items-end gap-3" @submit.prevent="newWorkspace">
            <div class="grid min-w-48 flex-1 gap-2"><Label for="mm-ws-new">New workspace</Label><Input id="mm-ws-new" v-model.trim="newName" maxlength="80" placeholder="Name" /></div>
            <Button variant="outline" :disabled="busy || !newName"><Plus aria-hidden="true" />Create</Button>
          </form>
        </template>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Team members</CardTitle>
        <CardDescription>Viewers read chats, projects and runs. Editors also ask the model and edit. Owners also manage people.</CardDescription>
        <CardAction><span class="text-muted-foreground text-sm">{{ data?.members.length || 0 }}</span></CardAction>
      </CardHeader>
      <CardContent class="grid gap-1">
        <div v-for="m in data?.members || []" :key="m.id" class="flex items-center gap-3 rounded-lg py-2">
          <Avatar :name="m.name || m.email || 'This computer'" />
          <div class="grid min-w-0 flex-1 gap-0.5">
            <p class="truncate text-sm leading-none font-medium">{{ m.name || m.email || 'This computer' }}<span v-if="m.id === data.you" class="text-muted-foreground font-normal"> (you)</span></p>
            <p v-if="m.email" class="text-muted-foreground truncate text-xs">{{ m.email }}</p>
          </div>
          <NativeSelect v-if="isOwner && signedIn" :model-value="m.role" class="h-8 w-28" :aria-label="`Role for ${m.name || m.email}`" @update:model-value="(r) => setRole(m, r)"><option v-for="r in roles" :key="r" :value="r">{{ r }}</option></NativeSelect>
          <Badge v-else variant="outline">{{ m.role }}</Badge>
          <Button v-if="signedIn && (m.id === data.you || isOwner)" variant="ghost" size="icon-sm" :aria-label="m.id === data.you ? 'Leave workspace' : `Remove ${m.name || m.email}`" :title="m.id === data.you ? 'Leave' : 'Remove'" @click="remove(m, m.id === data.you)"><component :is="m.id === data.you ? LogOut : UserMinus" aria-hidden="true" /></Button>
        </div>
      </CardContent>
    </Card>

    <Card v-if="signedIn && isOwner">
      <CardHeader>
        <CardTitle>Invite teammates</CardTitle>
        <CardDescription>Anyone with the link can join once. No email is sent; share the link yourself.</CardDescription>
      </CardHeader>
      <CardContent class="grid gap-5">
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="invite">
          <div class="grid min-w-56 flex-1 gap-2"><Label for="mm-invite-email">Email (optional)</Label><Input id="mm-invite-email" v-model.trim="inviteEmail" type="email" placeholder="Leave empty for anyone with the link" maxlength="320" /></div>
          <div class="grid gap-2"><Label for="mm-invite-role">Role</Label><NativeSelect id="mm-invite-role" v-model="inviteRole" class="w-28"><option value="editor">editor</option><option value="viewer">viewer</option><option value="owner">owner</option></NativeSelect></div>
          <div class="grid gap-2"><Label for="mm-invite-days">Expires</Label><NativeSelect id="mm-invite-days" v-model.number="inviteDays" class="w-28"><option :value="1">1 day</option><option :value="7">7 days</option><option :value="30">30 days</option></NativeSelect></div>
          <Button :disabled="busy"><Link2 aria-hidden="true" />Create link</Button>
        </form>
        <div v-if="link" class="flex gap-2">
          <Input :model-value="link" readonly aria-label="Invitation link" class="h-9" @focus="$event.target.select()" />
          <Button variant="secondary" class="shrink-0" @click="copy"><component :is="copied ? Check : Copy" aria-hidden="true" />{{ copied ? 'Copied' : 'Copy link' }}</Button>
        </div>
        <template v-if="data?.invitations.length">
          <div class="bg-border h-px" role="separator"></div>
          <div class="grid gap-1">
            <p class="text-sm font-medium">Pending invitations</p>
            <div v-for="i in data.invitations" :key="i.id" class="flex items-center gap-3 py-2">
              <span class="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-full"><Mail class="size-4" aria-hidden="true" /></span>
              <div class="grid min-w-0 flex-1 gap-0.5"><p class="truncate text-sm leading-none font-medium">{{ i.email || 'Anyone with the link' }}</p><p class="text-muted-foreground text-xs">Expires {{ when(i.expires_at) }}</p></div>
              <Badge variant="outline">{{ i.role }}</Badge>
              <Button variant="ghost" size="sm" @click="revoke(i)">Revoke</Button>
            </div>
          </div>
        </template>
      </CardContent>
    </Card>

    <Card v-if="signedIn">
      <CardHeader>
        <CardTitle>Your account</CardTitle>
        <CardDescription>{{ account.account.email }}</CardDescription>
        <CardAction><Button variant="outline" size="sm" @click="logout"><LogOut aria-hidden="true" />Sign out</Button></CardAction>
      </CardHeader>
      <CardContent>
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="password">
          <div class="grid min-w-48 flex-1 gap-2"><Label for="mm-pw-current">Current password</Label><Input id="mm-pw-current" v-model="currentPassword" type="password" autocomplete="current-password" required /></div>
          <div class="grid min-w-48 flex-1 gap-2"><Label for="mm-pw-new">New password</Label><Input id="mm-pw-new" v-model="newPassword" type="password" autocomplete="new-password" minlength="12" required /></div>
          <Button variant="outline" :disabled="busy">Change password</Button>
        </form>
        <p v-if="passwordChanged" class="text-muted-foreground pt-3 text-sm" role="status">Password changed. Other browsers were signed out.</p>
      </CardContent>
    </Card>

    <Card v-if="!signedIn">
      <CardHeader>
        <CardTitle>Working with teammates</CardTitle>
        <CardDescription>This app runs for you alone on this computer.</CardDescription>
      </CardHeader>
      <CardContent class="text-muted-foreground grid gap-2 text-sm">
        <p>To share chats, projects and runs, run MarketMirror on a server with team accounts turned on (<code class="bg-muted rounded px-1 py-0.5 text-xs">MM_ACCOUNTS=on</code>). The steps are in <code class="bg-muted rounded px-1 py-0.5 text-xs">docs/ACCOUNTS.md</code>.</p>
        <p>Your chats and projects here are already kept in this computer's database.</p>
      </CardContent>
    </Card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Check, Copy, Link2, LogOut, Mail, Plus, UserMinus } from 'lucide-vue-next'
import { Avatar } from '../ui/avatar'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { NativeSelect } from '../ui/native-select'
import { account as accountState, changePassword, createWorkspace, isOwner, role, selectWorkspace, signedIn, signOut, team } from '../../workspace/account.js'
import { api } from '../../workspace/api.js'

const router = useRouter()
const account = computed(() => accountState.value)
const roles = ['owner', 'editor', 'viewer']
const data = ref(null), error = ref(''), busy = ref(false)
const workspaceName = ref(''), newName = ref('')
const inviteEmail = ref(''), inviteRole = ref('editor'), inviteDays = ref(7), link = ref(''), copied = ref(false)
const currentPassword = ref(''), newPassword = ref(''), passwordChanged = ref(false)
const roleText = (r) => ({ owner: 'an owner', editor: 'an editor', viewer: 'a viewer' })[r] || r
const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
const intro = computed(() => signedIn.value ? "Everyone here shares this workspace's chats, projects and saved runs." : 'Single-user mode on this computer.')

async function load() {
  try { data.value = signedIn.value ? await team.get() : await api('/api/team'); workspaceName.value = data.value.workspace.name; error.value = '' }
  catch (err) { error.value = err.message }
}
async function act(fn) {
  busy.value = true; error.value = ''
  try { await fn(); await load() } catch (err) { error.value = err.message } finally { busy.value = false }
}
const rename = () => act(async () => { if (signedIn.value) await team.rename(workspaceName.value); else await api('/api/team/workspace', { method: 'PATCH', body: { name: workspaceName.value } }); window.dispatchEvent(new Event('mm-workspace-renamed')) })
const switchTo = (id) => act(() => selectWorkspace(id))
const newWorkspace = () => act(async () => { await createWorkspace(newName.value); newName.value = '' })
function setRole(m, r) {
  const self = m.id === data.value.you
  if (roleChangeNeedsConfirmation(m, r, data.value.you)) {
    const who = self ? 'your own' : `${m.name || m.email}'s`
    const message = self
      ? `Change your own role to ${r}? You may lose access to owner actions.`
      : `Demote ${who} role from owner to ${r}?`
    if (!confirm(message)) return
  }
  act(() => team.setRole(m.id, r))
}
function remove(m, self) {
  if (!confirm(self ? `Leave ${data.value.workspace.name}? You lose access until someone invites you again.` : `Remove ${m.name || m.email} from this workspace?`)) return
  act(async () => { await team.remove(m.id); if (self) { const other = account.value.workspaces.find(w => w.id !== data.value.workspace.id); if (other) await selectWorkspace(other.id); router.replace('/') } })
}
const invite = () => act(async () => { const made = await team.invite({ email: inviteEmail.value || null, role: inviteRole.value, expires_in_days: inviteDays.value }); link.value = made.url; copied.value = false; inviteEmail.value = '' })
const revoke = (i) => act(() => team.revoke(i.id))
async function copy() { try { await navigator.clipboard.writeText(link.value); copied.value = true } catch { error.value = 'Copy the link by hand: select it and copy.' } }
const password = () => act(async () => { await changePassword(currentPassword.value, newPassword.value); currentPassword.value = newPassword.value = ''; passwordChanged.value = true })
async function logout() { await signOut(); router.replace('/login') }

onMounted(load)
watch(() => account.value.workspace?.id, load)
</script>

<style>
/* The workspace shell styles headings and paragraphs; these cards use the shadcn spacing instead. */
.ws .mm-team h1, .ws .mm-team h3, .ws .mm-team p { margin: 0; }
/* shadcn assumes Tailwind's preflight, which sets every border to the border token; this app does not load it. */
@layer base { .mm-team *, .mm-team *::before, .mm-team *::after { border-color: var(--line); } }
</style>
