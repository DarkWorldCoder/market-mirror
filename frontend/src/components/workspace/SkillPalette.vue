<script setup>
import { computed, nextTick, ref, watch, onBeforeUnmount } from 'vue'
import { ArrowUpRight, Search } from 'lucide-vue-next'
import { Command, CommandList, CommandGroup, CommandItem } from '../ui/command'
import { searchFeatures } from '../../workspace/featureCatalog'

const props = defineProps({ open: Boolean, query: { type: String, default: '' }, theme: { default: 'light' } })
const emit = defineEmits(['select', 'close'])
const items = computed(() => searchFeatures(props.query))
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
function handleKey(event) {
  if (!props.open) return false
  if (event.key === 'Escape') { event.preventDefault(); emit('close'); return true }
  if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
    event.preventDefault()
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : -1) + items.value.length) % (items.value.length || 1)
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
    <div class="skill-palette-heading"><Search :size="15" /><span>Skills & actions</span><span class="skill-palette-count">{{ items.length }} available</span></div>
    <Command class="skill-command">
      <CommandList ref="list" aria-label="Available skills" tabindex="0" class="skill-list">
        <p v-if="!items.length" class="skill-empty">No matching skills. Try “ads”, “memory”, or “pricing”.</p>
        <CommandGroup v-for="group in [...new Set(items.map(item => item.group))]" :key="group" :heading="group">
          <CommandItem v-for="item in items.filter(item => item.group === group)" :key="item.id" :value="item.id" :data-active="items.indexOf(item) === active" class="skill-row" @select="choose(item)" @pointermove="active = items.indexOf(item)" @mousedown.prevent>
            <span class="skill-copy"><span class="skill-title">{{ item.label }} <code>{{ item.command }}</code></span><span class="skill-description">{{ item.description }}</span></span>
            <ArrowUpRight :size="15" />
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </Command>
    <div class="skill-palette-footer"><span>↑ ↓ Navigate · Enter Choose · Esc Close</span><span>Experiments use your configured provider</span></div>
  </section></Teleport></span>
</template>

<style scoped>
.skill-anchor{display:contents}.skill-palette{display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:20px;background:var(--panel);box-shadow:0 18px 60px #24213b20;color:var(--text)}
.skill-palette-heading{flex-shrink:0;display:flex;align-items:center;gap:9px;padding:15px 18px 11px;font-size:13px;font-weight:650}.skill-palette-count{margin-left:auto;color:var(--muted);font-size:11px;font-weight:400}.skill-command{min-height:0;flex:1;overflow:hidden;background:transparent!important;color:inherit!important}.skill-list{max-height:100%!important;height:100%;overflow-y:auto;padding:0 7px 8px}.skill-list :deep([data-slot=command-group-heading]){padding:12px 11px 6px;color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}.skill-row{padding:11px!important;gap:15px!important;border-radius:11px!important;cursor:pointer!important}.skill-row[data-active=true]{background:color-mix(in srgb,var(--accent) 10%,transparent)!important}.skill-copy{display:flex;flex:1;flex-direction:column;gap:4px;min-width:0}.skill-title{font-size:13px;font-weight:550}.skill-title code{margin-left:7px;color:var(--muted);font-size:11px;font-weight:400}.skill-description{color:var(--muted);font-size:11px;line-height:1.5}.skill-palette-footer{flex-shrink:0;display:flex;justify-content:space-between;gap:12px;padding:10px 18px;border-top:1px solid var(--line);color:var(--muted);font-size:10px}.skill-empty{padding:25px 16px;color:var(--muted);font-size:13px}@media(max-width:600px){.skill-palette-footer span:last-child{display:none}.skill-title code{display:none}}
</style>
