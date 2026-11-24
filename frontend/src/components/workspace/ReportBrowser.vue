<script setup>
import { computed, ref, watch } from 'vue'
import { FileChartColumn, ChartNoAxesCombined, MessagesSquare, Search, UsersRound } from 'lucide-vue-next'
import { TabsRoot, TabsList, TabsTrigger, TabsContent } from 'reka-ui'
import ChatArtifact from './ChatArtifact.vue'
import LoadingSkeleton from './LoadingSkeleton.vue'
import ExperimentHighlights from './ExperimentHighlights.vue'
import SocialFeedPlatform from './SocialFeedPlatform.vue'
import { Button } from '../ui/button'
import { preferredReport, reportInfo } from '../../workspace/reportPresentation'
import { api } from '../../workspace/api'

const props = defineProps({
  name: { type: String, required: true },
  files: { type: Array, default: () => [] },
  theme: { default: 'light' },
  initialView: { type: String, default: 'highlights' },
  reviewDisabled: Boolean
})
const emit = defineEmits(['review'])
const query = ref(''), selected = ref(''), view = ref('reports'), summary = ref(null)
const loading = ref(false), error = ref('')
let ticket = 0
const hasFeed = computed(() => props.files.some(file => ['feed_story.json', 'timeline.json', 'posts_reddit.json', 'posts_twitter.json', 'feed_test.json'].includes(file)))
const hasSummary = computed(() => props.files.includes('summary.json'))
const preferredView = computed(() => {
  if (props.initialView === 'social' && hasFeed.value) return 'social'
  if (props.initialView !== 'reports' && hasSummary.value) return 'highlights'
  return 'reports'
})
const filtered = computed(() => {
  const term = query.value.trim().toLowerCase()
  return props.files.filter(file => [reportInfo(file).title, file].some(label => label.toLowerCase().includes(term)))
})
const reportTitle = file => reportInfo(file).title

async function readSummary() {
  const request = ++ticket
  loading.value = true
  error.value = ''
  try {
    const data = await api(`/api/runs/${encodeURIComponent(props.name)}/files/summary.json`)
    if (request === ticket) summary.value = data
  } catch (failure) {
    if (request === ticket) error.value = failure.message
  } finally {
    if (request === ticket) loading.value = false
  }
}
watch(() => [props.name, props.files, props.initialView], () => {
  ++ticket
  query.value = ''
  summary.value = null
  error.value = ''
  loading.value = false
  selected.value = preferredReport(props.files)
  view.value = preferredView.value
  if (view.value === 'highlights') readSummary()
}, { immediate: true })
watch(view, value => {
  if (value === 'highlights' && !summary.value && !loading.value) readSummary()
})
</script>

<template>
  <section class="report-browser" aria-label="Saved reports">
    <TabsRoot v-model="view">
      <TabsList class="report-tabs workspace-modal-tabs" aria-label="Experiment views">
        <TabsTrigger v-if="hasSummary" value="highlights"><ChartNoAxesCombined :size="15" aria-hidden="true" />Highlights</TabsTrigger>
        <TabsTrigger v-if="hasFeed" value="social"><MessagesSquare :size="15" aria-hidden="true" />Social feed</TabsTrigger>
        <TabsTrigger value="reports"><FileChartColumn :size="15" aria-hidden="true" />Reports</TabsTrigger>
      </TabsList>
      <TabsContent v-if="hasSummary" value="highlights">
        <LoadingSkeleton v-if="loading" variant="cards" :lines="3" label="Loading saved highlights" />
        <p v-else-if="error" class="report-status" role="alert">{{ error }} <button class="ws-btn" @click="readSummary">Retry</button></p>
        <template v-else-if="summary">
          <div class="report-review-action">
            <Button type="button" size="sm" variant="outline" :disabled="reviewDisabled"
              @click="emit('review', { name, title: summary.project_name || name })">
              <UsersRound :size="15" aria-hidden="true" /> Review these results
            </Button>
          </div>
          <ExperimentHighlights :summary="summary" :can-open-feed="hasFeed" @open-feed="view = 'social'" />
        </template>
      </TabsContent>
      <TabsContent v-if="hasFeed" value="social">
        <SocialFeedPlatform v-if="view === 'social'" :name="name" :files="files" />
      </TabsContent>
      <TabsContent value="reports">
        <header>
          <p>{{ files.length }} saved files</p>
          <label><Search :size="15" aria-hidden="true" /><input v-model="query" type="search" placeholder="Search reports" aria-label="Search saved report files" /></label>
        </header>
        <div class="report-browser-layout">
          <nav aria-label="Report files">
            <button v-for="file in filtered" :key="file" :aria-pressed="selected === file" @click="selected = file">
              <FileChartColumn :size="16" aria-hidden="true" /><span>{{ reportTitle(file) }}<small>{{ reportInfo(file).category }}</small></span>
            </button>
            <p v-if="!filtered.length">No matching files.</p>
          </nav>
          <div class="report-detail">
            <ChatArtifact v-if="view === 'reports' && selected" :name="name" :file="selected" :title="reportTitle(selected)" :files="files" :theme="theme" />
            <p v-else-if="!selected">Choose a report to explore.</p>
          </div>
        </div>
      </TabsContent>
    </TabsRoot>
  </section>
</template>

<style scoped>
.report-browser { margin-top: 16px; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: var(--panel); min-width: 0; }
.report-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 7px 10px; border-bottom: 1px solid var(--line); background: var(--panel-2); }
.report-tabs button { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; cursor: pointer; }
.report-status { margin: 12px; font-size: 13px; }
.report-review-action { display: flex; justify-content: flex-end; padding: 11px 14px 0; }
.report-browser header { display: flex; justify-content: space-between; gap: 8px; align-items: center; padding: 12px; border-bottom: 1px solid var(--line); }
.report-browser header p { font-size: 12px; color: var(--muted); margin: 0; white-space: nowrap; }
.report-browser header label { display: flex; gap: 6px; align-items: center; border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; max-width: 65%; }
.report-browser input { width: 100%; min-width: 0; font-size: 12px; }
.report-browser-layout { display: grid; grid-template-columns: 180px minmax(0,1fr); }
.report-browser nav { max-height: 560px; overflow: auto; padding: 8px; border-right: 1px solid var(--line); }
.report-browser nav button { display: flex; align-items: flex-start; gap: 8px; text-align: left; width: 100%; padding: 9px; border-radius: 8px; cursor: pointer; font-size: 12px; line-height: 1.4; }
.report-browser nav button[aria-pressed=true] { background: var(--accent-2); }
.report-browser nav svg { flex-shrink: 0; margin-top: 2px; }
.report-browser nav small { display: block; font-size: 11px; color: var(--muted); overflow-wrap: anywhere; margin-top: 3px; }
.report-detail { min-width: 0; padding: 0 12px 12px; max-height: 620px; overflow: auto; }
.report-detail :deep(.chat-artifact) { padding: 12px; border: 0; margin-top: 0; }
.report-detail :deep(.chat-artifact header) { padding: 10px 0; }
.report-detail :deep(.chat-artifact-content) { max-height: none; }
@media(max-width:620px) {
  .report-browser-layout { grid-template-columns: 1fr; }
  .report-browser nav { max-height: 160px; border-right: 0; border-bottom: 1px solid var(--line); }
}
</style>
