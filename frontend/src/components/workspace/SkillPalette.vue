<script setup>
import { computed, nextTick, ref, watch, onBeforeUnmount } from 'vue'
import { ArrowUpRight, Search } from 'lucide-vue-next'
import { Command, CommandList, CommandGroup, CommandItem } from '../ui/command'
import { searchFeatures } from '../../workspace/featureCatalog'

const props = defineProps({ open: Boolean, query: { type: String, default: '' }, theme: { default: 'light' } })
const emit = defineEmits(['select', 'close'])
// best matches first, kept together by group so the arrow keys move in the order the list shows
const items = computed(() => { const hits = searchFeatures(props.query); return [...new Set(hits.map(i => i.group))].flatMap(g => hits.filter(i => i.group === g)) })
const active = ref(0)
const list = ref(null), anchor = ref(null), placement = ref({})
let observer
function positionMenu() {
  const region = anchor.value?.parentElement
  if (!region) return
  const r = region.getBoundingClientRect(), margin = 12
  const above = r.top - margin * 2, below = innerHeight - r.bottom - margin * 2
  const height = Math.max(100, Math.min(420, Math.max(above, below)))
  const top = above >= below ? Math.max(margin, r.top - height - 8) : Math.min(innerHeight - height - margin, r.bottom + 8)
  placement.value = { position: 'fixed', top: `${top}px`, left: `${Math.max(margin, Math.min(r.left, innerWidth - Math.min(r.width, innerWidth - margin * 2) - margin))}px`, width: `${Math.min(r.width, innerWidth - margin * 2)}px`, height: `${height}px`, zIndex: 70 }
}
watch(() => props.open, async open => {
  observer?.disconnect(); window.removeEventListener('resize', positionMenu); window.removeEventListener('scroll', positionMenu, true)
  if (!open) return
  await nextTick(); positionMenu()
  observer = new ResizeObserver(positionMenu); if (anchor.value?.parentElement) observer.observe(anchor.value.parentElement)
  window.addEventListener('resize', positionMenu); window.addEventListener('scroll', positionMenu, true)
})
onBeforeUnmount(() => { observer?.disconnect(); window.removeEventListener('resize', positionMenu); window.removeEventListener('scroll', positionMenu, true) })
watch(() => props.query, () => { active.value = 0 })
function choose(item) { if (item) emit('select', item) }
const costTitle = (item) => (item.cost === 'free'
  ? 'Free: shown from saved files or a local page, no model call'
  : 'Goes to the chat agent; anything that runs simulated buyers shows its cost for your approval first')
function handleKey(event) {
  if (!props.open) return false
  if (event.key === 'Escape') { event.preventDefault(); emit('close'); return true }
  if (['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp'].includes(event.key) || ((event.key === 'Home' || event.key === 'End') && event.ctrlKey)) {
    event.preventDefault()
    const n = items.value.length || 1
    if (event.key === 'Home') active.value = 0
    else if (event.key === 'End') active.value = n - 1
    else if (event.key === 'PageDown') active.value = Math.min(n - 1, active.value + 5)
    else if (event.key === 'PageUp') active.value = Math.max(0, active.value - 5)
    else active.value = (active.value + (event.key === 'ArrowDown' ? 1 : -1) + n) % n
    nextTick(() => list.value?.$el?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' }))
    return true
  }
  if (event.key === 'Enter' && !event.shiftKey && items.value.length) { event.preventDefault(); choose(items.value[active.value]); return true }
  return false
}
defineExpose({ handleKey })
</script>

<template>
  <span ref="anchor" class="skill-anchor"><Teleport to="body"><section v-if="open" :style="placement" :data-theme="theme" class="skill-palette ws-overlay" aria-label="MarketMirror skills" @keydown="handleKey">
    <div class="skill-palette-heading"><Search :size="15" aria-hidden="true" /><span>Skills & actions</span><span class="skill-palette-count" role="status" aria-live="polite">{{ items.length }} available</span></div>
    <Command class="skill-command">
      <CommandList ref="list" aria-label="Available skills" tabindex="0" class="skill-list">
        <p v-if="!items.length" class="skill-empty">No matching skills. Try “ads”, “memory”, or “pricing”.</p>
        <CommandGroup v-for="group in [...new Set(items.map(item => item.group))]" :key="group" :heading="group">
          <CommandItem v-for="item in items.filter(item => item.group === group)" :key="item.id" :value="item.id" :data-active="items.indexOf(item) === active" class="skill-row" @select="choose(item)" @pointermove="active = items.indexOf(item)" @mousedown.prevent>
            <span class="skill-copy"><span class="skill-title">{{ item.label }} <code>{{ item.command }}</code></span><span class="skill-description">{{ item.description }}</span></span>
            <span class="skill-cost" :class="item.cost === 'free' ? 'free' : 'asks'" :title="costTitle(item)">{{ item.cost === 'free' ? 'Free' : 'Asks first' }}<span class="sr-only">: {{ costTitle(item) }}</span></span>
            <ArrowUpRight :size="15" aria-hidden="true" />
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </Command>
    <div class="skill-palette-footer"><span>↑ ↓ Navigate · Enter Choose · Esc Close</span><span>Free ones show saved data · Asks first shows the cost before spending</span></div>
  </section></Teleport></span>
</template>

<style scoped>
.skill-anchor{display:contents}.skill-palette{display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:20px;background:var(--panel);box-shadow:0 18px 60px #24213b20;color:var(--text)}
.skill-palette-heading{flex-shrink:0;display:flex;align-items:center;gap:9px;padding:15px 18px 11px;font-size:13px;font-weight:650}.skill-palette-count{margin-left:auto;color:var(--muted);font-size:11px;font-weight:400}.skill-command{min-height:0;flex:1;overflow:hidden;background:transparent!important;color:inherit!important}.skill-list{max-height:100%!important;height:100%;overflow-y:auto;padding:0 7px 8px}.skill-list :deep([data-slot=command-group-heading]){padding:12px 11px 6px;color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}.skill-row{padding:11px!important;gap:15px!important;border-radius:11px!important;cursor:pointer!important}.skill-row[data-active=true]{background:color-mix(in srgb,var(--accent) 10%,transparent)!important}.skill-copy{display:flex;flex:1;flex-direction:column;gap:4px;min-width:0}.skill-title{font-size:13px;font-weight:550}.skill-title code{margin-left:7px;color:var(--muted);font-size:11px;font-weight:400}.skill-description{color:var(--muted);font-size:11px;line-height:1.5}.skill-palette-footer{flex-shrink:0;display:flex;justify-content:space-between;gap:12px;padding:10px 18px;border-top:1px solid var(--line);color:var(--muted);font-size:10px}.skill-empty{padding:25px 16px;color:var(--muted);font-size:13px}.skill-cost{flex-shrink:0;padding:1px 8px;border:1px solid var(--line);border-radius:999px;font-size:10.5px;font-weight:600;line-height:1.7;white-space:nowrap}.skill-cost.free{color:var(--yes,#2f8f5b);border-color:color-mix(in srgb,var(--yes,#2f8f5b) 45%,var(--line))}.skill-cost.asks{color:var(--warm,var(--muted));border-color:color-mix(in srgb,var(--warm,#a87a1c) 45%,var(--line))}@media(max-width:600px){.skill-palette-footer span:last-child{display:none}.skill-title code{display:none}}
</style>
