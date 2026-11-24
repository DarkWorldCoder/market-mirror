<template>
  <!-- the agent's open_view lands on the same in-chat run card as saved runs opened from the sidebar -->
  <RunChatCard class="agent-view" :name="artifact.run" :initial-tab="tabForView(artifact.view)" :runs="runs" :theme="theme" @action="(a) => emit('action', a)" @loaded="(d) => emit('loaded', d)" />
</template>
<script setup>
import { defineAsyncComponent } from 'vue'
import { tabForView } from '../../../workspace/runCard.js'
const RunChatCard = defineAsyncComponent(() => import('../RunChatCard.vue'))
defineProps({ artifact: { type: Object, required: true }, runs: { type: Array, default: () => [] }, theme: { type: String, default: 'light' } })
const emit = defineEmits(['action', 'loaded'])
</script>
