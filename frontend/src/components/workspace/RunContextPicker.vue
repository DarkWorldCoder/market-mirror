<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child><Button variant="ghost" size="sm" :disabled="disabled" role="combobox" :aria-expanded="open" aria-label="Choose saved run context" class="run-context-trigger"><Database /><span>{{ selected?.title || 'All workspace' }}</span><ChevronDown /></Button></PopoverTrigger>
    <PopoverContent align="start" side="top" :collision-padding="12" :side-offset="8" :avoid-collisions="true" class="ws-overlay run-context-popup w-80 p-0" :data-theme="theme">
      <Command><CommandInput placeholder="Search saved runs…" aria-label="Search saved runs" /><CommandList aria-label="Saved run choices" tabindex="0"><CommandEmpty>No matching runs.</CommandEmpty><CommandGroup heading="Conversation context"><CommandItem value="All workspace" @select="choose('')"><FolderOpen />All workspace<Check v-if="!modelValue" class="ml-auto" /></CommandItem></CommandGroup><CommandGroup heading="Saved experiments"><CommandItem v-for="r in runs" :key="r.name" :value="`${r.title} ${r.name}`" @select="choose(r.name)"><FileChartColumn /><span class="run-choice"><b>{{ r.title || r.name }}</b><small>{{ r.people == null ? 'Saved results' : `${r.people} simulated participants` }}</small></span><Check v-if="modelValue === r.name" class="ml-auto" /></CommandItem></CommandGroup></CommandList></Command>
    </PopoverContent>
  </Popover>
</template>
<script setup>
import { computed, ref } from 'vue'
import { Database, ChevronDown, FolderOpen, FileChartColumn, Check } from 'lucide-vue-next'
import { Button } from '../ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover'
import { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem } from '../ui/command'
const props = defineProps({ modelValue: { type: String, default: '' }, runs: { type: Array, default: () => [] }, disabled: Boolean, theme: { type:String, default:'light' } })
const emit = defineEmits(['update:modelValue']), open = ref(false)
const selected = computed(() => props.runs.find(r => r.name === props.modelValue))
defineExpose({openPicker: () => { open.value = true }})
function choose(name) { emit('update:modelValue', name); open.value = false }
</script>
<style scoped>
.run-context-trigger{max-width:260px}.run-context-trigger>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:190px}.run-choice{min-width:0;display:flex;flex-direction:column;gap:3px;white-space:normal;line-height:1.5}.run-choice b{font-weight:500;font-size:13px}.run-choice small{font-size:11px;color:var(--muted)}

:global(.ws .direct-chat .direct-composer-options>button.run-context-trigger){height:30px;min-height:30px;padding:6px 8px!important;gap:6px;border-radius:8px;font-size:12px;line-height:18px;font-weight:400}
:global(.ws .direct-chat .direct-composer-options>button.run-context-trigger>svg){width:14px;height:14px;flex-shrink:0}
:global(.ws .direct-chat .direct-composer-options>button.run-context-trigger:hover){background:var(--panel-2);color:var(--text)}
:global(.ws .direct-chat .direct-composer-options>button.run-context-trigger:focus-visible){outline:2px solid var(--accent);outline-offset:2px}
:global(.ws .direct-chat .direct-composer-options>button.run-context-trigger:disabled){opacity:.5;cursor:default}
.run-context-popup :deep([data-slot=command-group-heading]){font-size:12px;line-height:18px}.run-context-popup :deep([data-slot=command-item]){font-size:13px;line-height:20px;padding:10px 12px;gap:9px}.run-context-popup :deep([data-slot=command-item]>svg){width:16px;height:16px}.run-context-popup .run-choice b{font-size:13px;line-height:20px}.run-context-popup .run-choice small{font-size:12px;line-height:18px}
</style>
