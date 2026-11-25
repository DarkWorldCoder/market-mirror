<template>
  <!-- Layout from the shadcn-vue login block (centered card on a muted page), with the team-invite accept block's banner. -->
  <main class="mm-auth bg-muted text-foreground flex min-h-svh flex-col items-center justify-center gap-6 p-6 md:p-10" :data-theme="theme">
    <div class="flex w-full max-w-sm flex-col gap-6">
      <a href="/" class="text-foreground flex items-center gap-2 self-center text-sm font-medium no-underline"><MarketMirrorLogo :size="24" />MarketMirror</a>

      <Card>
        <CardHeader class="text-center">
          <CardTitle class="text-xl">{{ heading }}</CardTitle>
          <CardDescription>{{ subheading }}</CardDescription>
        </CardHeader>
        <CardContent class="grid gap-6">
          <div v-if="invite" class="bg-muted/60 flex items-center gap-3 rounded-lg border p-3">
            <Avatar :name="invite.workspace" class="size-10 text-sm" />
            <div class="grid min-w-0 flex-1 gap-0.5 text-sm">
              <span class="truncate font-medium">{{ invite.workspace }}</span>
              <span class="text-muted-foreground truncate text-xs">{{ invite.email || 'Anyone with this link' }} · expires {{ when(invite.expires_at) }}</span>
            </div>
            <Badge variant="secondary">{{ invite.role }}</Badge>
          </div>
          <p v-if="inviteError" class="text-destructive text-sm" role="alert">{{ inviteError }}</p>

          <div v-if="signedIn && invite" class="grid gap-3">
            <p class="text-muted-foreground text-center text-sm">Signed in as {{ account.account.email }}.</p>
            <p v-if="error" class="text-destructive text-sm" role="alert">{{ error }}</p>
            <Button class="w-full" :disabled="busy" @click="join">Join {{ invite.workspace }}</Button>
          </div>

          <form v-else class="grid gap-5" @submit.prevent="submit">
            <div v-if="screen === 'signup'" class="grid gap-2">
              <Label for="mm-name">Your name</Label>
              <Input id="mm-name" v-model.trim="name" autocomplete="name" maxlength="80" placeholder="Sam Rivera" />
            </div>
            <div class="grid gap-2">
              <Label for="mm-email">Email</Label>
              <Input id="mm-email" v-model.trim="email" type="email" autocomplete="email" required maxlength="320" placeholder="you@company.com" />
            </div>
            <div class="grid gap-2">
              <Label for="mm-password">Password</Label>
              <Input id="mm-password" v-model="password" type="password" :autocomplete="screen === 'signup' ? 'new-password' : 'current-password'" required minlength="12" maxlength="256" />
              <p v-if="screen === 'signup'" class="text-muted-foreground text-xs">At least 12 characters.</p>
            </div>
            <div v-if="screen === 'signup' && !invite" class="grid gap-2">
              <Label for="mm-workspace">Workspace name</Label>
              <Input id="mm-workspace" v-model.trim="workspaceName" maxlength="80" placeholder="Acme marketing" />
            </div>
            <p v-if="error" class="text-destructive text-sm" role="alert">{{ error }}</p>
            <Button type="submit" class="w-full" :disabled="busy">
              <LoaderCircle v-if="busy" class="animate-spin" aria-hidden="true" />
              {{ screen === 'signup' ? (invite ? 'Create account and join' : 'Create account') : (invite ? 'Sign in and join' : 'Sign in') }}
            </Button>
          </form>

          <p v-if="!signedIn" class="text-center text-sm">
            <template v-if="screen === 'signup'">Already have an account? <button type="button" class="underline underline-offset-4" @click="screen = 'login'">Sign in</button></template>
            <template v-else>New here? <button type="button" class="underline underline-offset-4" @click="screen = 'signup'">Create an account</button></template>
          </p>
        </CardContent>
      </Card>

      <p class="text-muted-foreground text-center text-xs text-balance">MarketMirror tests ideas on simulated buyers. Its results are simulated directions, not measurements of real people.</p>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LoaderCircle } from 'lucide-vue-next'
import MarketMirrorLogo from '../components/MarketMirrorLogo.vue'
import { Avatar } from '../components/ui/avatar'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { account as accountState, acceptInvitation, invitationFromHash, previewInvitation, signedIn, signIn, signUp } from '../workspace/account.js'
import { chooseTheme, storedTheme } from '../workspace/theme.js'

const props = defineProps({ mode: { type: String, default: 'login' } })
const route = useRoute()
const router = useRouter()
const account = computed(() => accountState.value)
const PENDING = 'mm-pending-invite'
const screen = ref(props.mode === 'join' ? 'signup' : props.mode)
const name = ref(''), email = ref(''), password = ref(''), workspaceName = ref('')
const busy = ref(false), error = ref(''), inviteError = ref('')
const token = ref(''), invite = ref(null)
const theme = chooseTheme(storedTheme(), window.matchMedia?.('(prefers-color-scheme: dark)').matches)
const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
const heading = computed(() => invite.value ? `Join ${invite.value.workspace}` : screen.value === 'signup' ? 'Create your account' : 'Welcome back')
const subheading = computed(() => {
  if (invite.value) return screen.value === 'signup' ? 'Create an account to accept this invitation.' : 'Sign in to accept this invitation.'
  if (screen.value === 'login') return 'Sign in with your email and password.'
  if (account.value.first_account) return 'You are the first person here, so you will own the first workspace.'
  if (account.value.signups !== 'open') return 'Sign-up on this server needs an invitation link from a workspace owner.'
  return 'Start a workspace for your team.'
})

onMounted(() => { readInvite(); window.addEventListener('hashchange', readInvite) })
onUnmounted(() => window.removeEventListener('hashchange', readInvite))
async function readInvite() {
  inviteError.value = ''
  token.value = invitationFromHash() || (() => { try { return sessionStorage.getItem(PENDING) || '' } catch { return '' } })()
  if (location.hash) history.replaceState(history.state, '', location.pathname + location.search)
  if (!token.value) return
  try {
    sessionStorage.setItem(PENDING, token.value)
    invite.value = await previewInvitation(token.value)
    if (invite.value.email) email.value = invite.value.email
  } catch (err) {
    inviteError.value = err.message; token.value = ''; invite.value = null; sessionStorage.removeItem(PENDING)
  }
}

function done() {
  try { sessionStorage.removeItem(PENDING) } catch { /* nothing pending */ }
  const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') && !route.query.next.startsWith('//') ? route.query.next : '/'
  router.replace(next)
}

async function join() {
  busy.value = true; error.value = ''
  try { await acceptInvitation(token.value); done() } catch (err) { error.value = err.message } finally { busy.value = false }
}

async function submit() {
  busy.value = true; error.value = ''
  try {
    if (screen.value === 'signup') {
      await signUp({ email: email.value, password: password.value, name: name.value, ...(token.value ? { invitation: token.value } : { workspace_name: workspaceName.value || undefined }) })
    } else {
      await signIn(email.value, password.value)
      if (token.value) await acceptInvitation(token.value)
    }
    password.value = ''
    done()
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}
</script>

<style>
/* This page sits outside the workspace shell, so it carries the shell's colour tokens and form reset itself.
   The reset lives in the base layer so the shadcn utility classes still win. */
.mm-auth{--bg:#f6f7f9;--panel:#fff;--panel-2:#eef0f2;--line:#e5e9e7;--text:#17181a;--muted:#606a65;--accent:#1f6b4f;--accent-2:#e8f2ed;--no:#a43c31;--primary-foreground:#fff;font-family:'Geist',ui-sans-serif,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.mm-auth[data-theme='dark']{--bg:#161719;--panel:#1c1d20;--panel-2:#111214;--line:#2a2c30;--text:#ececec;--muted:#a4ada8;--accent:#5fc79a;--accent-2:#1b2b24;--no:#efaaa2;--primary-foreground:#0f1a15}
@layer base{.mm-auth *,.mm-auth *::before,.mm-auth *::after{border-color:var(--line)}.mm-auth button,.mm-auth input{appearance:none;background-color:transparent;border:0 solid var(--line);font:inherit;color:inherit;margin:0}.mm-auth button{cursor:pointer}.mm-auth h3,.mm-auth p{margin:0}}
</style>
