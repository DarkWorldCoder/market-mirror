<template>
  <section class="agent-view" :aria-label="title">
    <header><b>{{ title }}</b><SimulatedBadge /></header>
    <RunAudienceCard v-if="artifact.view === 'world_map' || artifact.view === 'audience'" :name="artifact.run" :theme="theme" />
    <ReportBrowser v-else :name="artifact.run" :files="artifact.files || []" :initial-view="artifact.view === 'social_feed' ? 'social' : 'highlights'" :theme="theme" review-disabled />
  </section>
</template>
<script setup>
import { computed, defineAsyncComponent } from 'vue'
import SimulatedBadge from './SimulatedBadge.vue'
const RunAudienceCard = defineAsyncComponent(() => import('../RunAudienceCard.vue'))
const ReportBrowser = defineAsyncComponent(() => import('../ReportBrowser.vue'))
const props = defineProps({ artifact: { type: Object, required: true }, theme: { type: String, default: 'light' } })
const NAMES = { world_map: 'World map', audience: 'Audience', reports: 'Reports', social_feed: 'Social feed' }
const title = computed(() => `${NAMES[props.artifact.view] || 'View'} · ${props.artifact.title || props.artifact.run}`)
</script>
<style scoped>
.agent-view { margin: 12px 0; }
.agent-view > header { display: flex; align-items: center; gap: 8px; font-size: 12px; margin-bottom: 6px; color: var(--muted); }
.agent-view > header b { font-weight: 550; color: var(--text); }
</style>
