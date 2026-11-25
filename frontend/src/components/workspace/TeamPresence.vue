<template>
  <div v-if="others.length" class="team-presence" :aria-label="description">
    <span class="sr-only" role="status" aria-live="polite">{{ announcement }}</span>
    <span class="team-presence-faces" aria-hidden="true">
      <span v-for="person in others.slice(0, 3)" :key="person.id" class="team-presence-face" :style="{ background: tint(person.id) }" :title="`${name(person)} · ${person.status}`">{{ initials(person) }}</span>
      <span v-if="others.length > 3" class="team-presence-more">+{{ others.length - 3 }}</span>
    </span>
    <span class="team-presence-label">{{ caption }}</span>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { cloudAccount } from '../../workspace/cloud.js'

const props = defineProps({ chatId: { type: String, default: '' }, busy: Boolean })
const people = ref([])
const announcement = ref('')
let known = null
const others = computed(() => people.value.filter(person => person.id !== cloudAccount.value?.account?.id))
const name = person => person.name || person.email?.split('@')[0] || 'Teammate'
const initials = person => name(person).split(/[\s._-]+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase()
const tint = id => ['#e6e8ff', '#e4f3ed', '#fbefcf'][[...String(id)].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 3]
const description = computed(() => others.value.map(person => `${person.email || name(person)} ${person.status === 'responding' ? 'is responding' : 'is viewing this conversation'}`).join(', '))
const caption = computed(() => {
  const responding = others.value.filter(person => person.status === 'responding')
  if (responding.length) return responding.length === 1 ? `${name(responding[0])} is responding` : `${responding.length} teammates responding`
  return others.value.length === 1 ? `${name(others.value[0])} is viewing` : `${others.value.length} teammates viewing`
})
let timer, controller, generation = 0, pending = false
async function heartbeat() {
  const current = cloudAccount.value
  if (!current?.workspace?.id || !props.chatId || document.hidden || pending) return
  const ownGeneration = generation
  pending = true
  controller = new AbortController()
  try {
    const response = await fetch('/auth/presence', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': current.csrf, 'X-MM-Workspace': current.workspace.id },
      body: JSON.stringify({ chat_id: props.chatId, status: props.busy ? 'responding' : 'viewing' }),
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(8000)])
    })
    if (!response.ok) throw new Error('Presence unavailable')
    const value = await response.json()
    if (ownGeneration === generation) people.value = Array.isArray(value.participants) ? value.participants : []
  } catch {
    if (ownGeneration === generation) people.value = []
  } finally {
    if (ownGeneration === generation) pending = false
  }
}
function reset() { generation++; controller?.abort(); pending = false; people.value = []; heartbeat() }
function visible() { if (!document.hidden) { people.value = []; heartbeat() } }
// Announce only joins and leaves; the caption changing on every heartbeat is
// not something a screen reader should read out.
watch(others, (list) => {
  const ids = list.map(person => person.id)
  if (known) {
    const joined = list.filter(person => !known.has(person.id))
    const left = [...known].filter(id => !ids.includes(id))
    const parts = []
    if (joined.length) parts.push(`${joined.map(name).join(', ')} joined`)
    if (left.length) parts.push(left.length === 1 ? 'A teammate left' : `${left.length} teammates left`)
    if (parts.length) announcement.value = parts.join('. ')
  }
  known = new Set(ids)
}, { deep: true })
watch(() => [props.chatId, cloudAccount.value?.workspace?.id], reset)
watch(() => props.busy, heartbeat)
onMounted(() => { heartbeat(); timer = setInterval(heartbeat, 15000); document.addEventListener('visibilitychange', visible) })
onBeforeUnmount(() => { generation++; controller?.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', visible) })
</script>

<style scoped>
.team-presence{display:flex;align-items:center;gap:9px;min-height:28px;min-width:0;color:var(--muted);font-size:12px;line-height:18px}.team-presence-faces{display:flex;align-items:center;padding-left:4px;flex-shrink:0}.team-presence-face,.team-presence-more{display:grid;place-items:center;width:26px;height:26px;border:2px solid var(--panel,#fff);border-radius:50%;margin-left:-4px;color:#37394b;font-size:9px;font-weight:600;line-height:1}.team-presence-more{background:var(--panel-2,#f4f4f9);color:var(--muted);font-size:9px}.team-presence-label{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}@media(max-width:540px){.team-presence{font-size:11px;gap:7px}.team-presence-label{max-width:180px}}
</style>
