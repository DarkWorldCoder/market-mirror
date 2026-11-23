<script setup>
import { computed, ref, watch } from 'vue'
import { Globe } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../ui/dialog'
import BrowserObservation from './BrowserObservation.vue'

const props = defineProps({
  open: Boolean,
  captures: { type: Array, default: () => [] },
  progress: { type: String, default: '' },
  theme: { type: String, default: 'light' }
})
const emit = defineEmits(['update:open'])
const selected = ref('')
const active = computed(() => props.captures.find(page => page.session_id === selected.value) || props.captures[0])
watch(() => props.open, open => { if (open) selected.value = '' })
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="ws-overlay browser-activity-panel" :data-theme="theme">
      <DialogHeader>
        <DialogTitle>Browser activity</DialogTitle>
        <DialogDescription>Pages captured for this conversation.</DialogDescription>
      </DialogHeader>
      <p v-if="progress" class="browser-panel-progress" role="status">{{ progress }}</p>
      <nav v-if="captures.length" class="browser-panel-list" aria-label="Captured pages">
        <button
          v-for="page in captures" :key="page.session_id" type="button"
          :aria-pressed="active?.session_id === page.session_id"
          @click="selected = page.session_id"
        >
          <Globe :size="15" aria-hidden="true" />
          <span><strong>{{ page.title || 'Captured page' }}</strong><small>{{ page.url }}</small></span>
        </button>
      </nav>
      <BrowserObservation v-if="active" :key="active.session_id" :observation="active" :theme="theme" />
      <p v-else-if="!progress" class="browser-panel-progress">Use View a website in the composer to capture a page.</p>
    </DialogContent>
  </Dialog>
</template>

<style>
.ws-overlay.browser-activity-panel {
  inset: 12px 12px 12px auto;
  transform: none;
  translate: none;
  width: min(500px, calc(100vw - 24px));
  max-width: none;
  max-height: calc(100dvh - 24px);
  display: block;
  margin: 0;
  padding: 18px;
  overflow: auto;
  overscroll-behavior: contain;
  border-color: var(--line);
  border-radius: 14px;
  background: var(--panel);
  color: var(--text);
}
.browser-activity-panel [data-slot=dialog-header] { padding-inline-end: 28px; }
.browser-panel-progress { font-size: 13px; color: var(--muted); margin: 12px 0 0; }
.browser-panel-list { display: grid; gap: 5px; margin: 13px 0 0; max-height: 210px; overflow: auto; }
.browser-panel-list > button { display: flex; align-items: center; gap: 8px; text-align: left; border: 1px solid var(--line); padding: 7px 9px; border-radius: 8px; cursor: pointer; }
.browser-panel-list > button[aria-pressed=true] { background: var(--panel-2); border-color: var(--accent); }
.browser-panel-list > button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.browser-panel-list svg { flex-shrink: 0; }
.browser-panel-list span { display: grid; min-width: 0; gap: 3px; }
.browser-panel-list strong, .browser-panel-list small { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.browser-panel-list strong { font-size: 12px; }
.browser-panel-list small { font-size: 11px; color: var(--muted); }
@media (max-width: 480px) { .ws-overlay.browser-activity-panel { padding: 14px; } }
</style>
