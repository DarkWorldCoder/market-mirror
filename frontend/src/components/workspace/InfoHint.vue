<script setup>
import { Info } from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover'
defineProps({ label: { type: String, default: 'More information' }, theme: { type: String, default: 'light' } })
</script>
<template><Popover><PopoverTrigger as-child><button type="button" class="settings-info-trigger" :aria-label="label"><Info :size="15" /></button></PopoverTrigger><PopoverContent class="ws-overlay settings-info-popover" :data-theme="theme" align="end" side="top"><p><slot /></p></PopoverContent></Popover></template>
<style scoped>
.settings-info-trigger{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;padding:0;flex-shrink:0;border:0;border-radius:7px;background:transparent;color:var(--muted);cursor:pointer}.settings-info-trigger:hover{background:var(--panel-2);color:var(--text)}.settings-info-trigger:focus-visible{outline:2px solid var(--accent);outline-offset:2px}:global(.settings-info-popover){width:min(320px,calc(100vw - 32px));padding:16px!important;border:1px solid var(--line)!important;border-radius:12px!important;background:var(--panel)!important;color:var(--text)!important;z-index:100!important}.settings-info-popover p{font-size:12px;line-height:1.8;margin:0}
</style>
