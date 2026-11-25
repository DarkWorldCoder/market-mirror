<template>
  <!-- the agent's open_view: run views land on the same in-chat run card as saved runs opened from the sidebar (at the
       matching tab, with any filters); compare embeds the comparison; workspace views get their own card -->
  <RunChatCard v-if="kind === 'run' && artifact.run" class="agent-view" :name="artifact.run" :initial-tab="viewTab(artifact.view)" :filters="artifact.filters || null" :initial-verdict="artifact.filters?.verdict || ''" :runs="runs" :theme="theme" @action="(a) => emit('action', a)" @loaded="(d) => emit('loaded', d)" />
  <CompareRuns v-else-if="kind === 'compare'" class="agent-view" embedded :runs="runs" :theme="theme" :a="pair.a" :b="pair.b" @pick="(p) => { pair = { a: p.a || '', b: p.b || '' } }" />
  <ChatViewCard v-else-if="kind === 'workspace'" class="agent-view" :spec="artifact" :runs="runs" :theme="theme" @panel="(panel) => emit('action', { type: 'open-panel', panel })" @feature="(feature) => emit('action', { type: 'feature', feature })" @open-run="(run) => emit('action', { type: 'open-run', run })" />
</template>
<script setup>
import { computed, defineAsyncComponent, ref } from 'vue'
import { CHAT_VIEWS, viewTab } from '../../../workspace/chatViews.js'
const RunChatCard = defineAsyncComponent(() => import('../RunChatCard.vue'))
const CompareRuns = defineAsyncComponent(() => import('../CompareRuns.vue'))
const ChatViewCard = defineAsyncComponent(() => import('../ChatViewCard.vue'))
const props = defineProps({ artifact: { type: Object, required: true }, runs: { type: Array, default: () => [] }, theme: { type: String, default: 'light' } })
const emit = defineEmits(['action', 'loaded'])
// older saved chats have views from before this list (world_map, reports, social_feed, audience): all run views
const kind = computed(() => CHAT_VIEWS[props.artifact.view]?.kind || (props.artifact.run ? 'run' : ''))
const pair = ref({ a: props.artifact.runs?.[0] || '', b: props.artifact.runs?.[1] || '' })
</script>
