<template>
  <div class="direct-chat" :class="{ started: messages.length }">
    <div v-if="messages.length" class="direct-project-toolbar"><button @click="openProjectPicker"><FolderOpen :size="14" />{{ activeProject?.name || 'Add chat to a project' }}<ChevronRight :size="13" /></button><button v-if="activeProject" @click="knowledgeOpen = true">Project context</button><button v-if="browserCaptures.length || browserProgress" type="button" class="direct-browser-toggle" @click="browserActivityOpen = true"><Globe :size="14" />Browser activity</button></div>
    <TeamPresence v-if="cloudAccount && conversationId" :chat-id="conversationId" :busy="busy && answerMode !== 'note'" />
    <div ref="scrollArea" class="direct-scroll" tabindex="0" role="region" aria-label="Conversation">
      <div v-if="!messages.length" class="direct-welcome">
        <p v-if="!activeProject" class="dw-greet">{{ greeting }}</p>
        <h1>{{ activeProject ? activeProject.name : 'What do you want to explore?' }}</h1>
        <p class="dw-sub">{{ activeProject?.description || 'Ask a question, test an idea, or explore your results.' }}</p>
        <p v-if="!activeProject && latestRun" class="dw-context">
          {{ runs.length }} saved {{ plural(runs.length, { one: 'experiment', other: 'experiments' }) }} · latest:
          <RouterLink :to="{ path: '/', query: { run: latestRun.name, show: 'reports' } }" :title="latestRun.title || latestRun.name">{{ shortTitle(latestRun.title || latestRun.name, 48) }}</RouterLink>
          <span v-if="latestRun.decision" class="dw-decision" :class="decisionTone(latestRun.decision)">Simulated verdict: {{ decisionText(latestRun.decision) }}</span>
        </p>
        <button v-if="activeProject" class="direct-project-edit" @click="knowledgeOpen = true">Project context</button><button v-if="activeProject" class="direct-project-edit" @click="editProject">Edit project</button>
        <button class="direct-project-edit" @click="openSkills">Browse all {{ featureCatalog.length }} skills</button>
        <button class="direct-project-edit" @click="openProjectPicker">{{ activeProject ? 'Choose another project' : 'Choose a project' }}</button>

      </div>
      <div v-else class="direct-messages">
        <article v-for="m in messages" :key="m.id" class="direct-message" :class="[m.role,{'other-member':m.role === 'user' && m.author && m.author.id !== cloudAccount?.account.id}]">
          <div v-if="m.role === 'assistant'" class="direct-message-label"><MarketMirrorLogo class="direct-mini-mark" :size="23" />MarketMirror</div>
          <MarkdownText v-if="m.role === 'assistant'" :text="m.content" /><div v-else class="direct-message-text">{{ m.content }}</div>
          <p v-if="m.kind === 'comment' || (m.role === 'user' && m.author && m.author.id !== cloudAccount?.account.id)" class="direct-author">{{ m.author?.email || 'You' }}{{ m.kind === 'comment' ? ' · Team note' : '' }}</p>
          <UploadedContext v-if="m.attachedFiles?.length" :files="m.attachedFiles" :theme="theme" />
          <RunChatCard v-if="m.run_card" :name="m.run_card.run" :initial-tab="m.run_card.tab" :initial-verdict="m.run_card.verdict || ''" :filters="m.run_card.filters || null" :runs="runs" :theme="theme" @action="runCardAction" @loaded="rememberRun" @update:tab="(t) => { m.run_card.tab = t; persist() }" />
          <ChatViewCard v-if="m.view_card" :spec="m.view_card" :runs="runs" :theme="theme" @panel="openPanel" @feature="selectFeature" @open-run="(run) => openEvidenceInChat(run, 'results')" />
          <CompareRuns v-if="m.compare" embedded :runs="runs" :theme="theme" :a="m.compare.a" :b="m.compare.b" @pick="(p) => updateCompare(m, p)" />
          <!-- [agent-chat] chat agent cards: tools, approvals, forms, audience table (components/workspace/agent) -->
          <AgentTurn v-if="m.agent" :turn="m.agent" :runs="runs" :theme="theme" :busy="busy" @run-action="runCardAction" @run-loaded="rememberRun" @resume="(r) => resumeAgent(m, r)" @action="agentAction" @open-run="(run) => openEvidenceInChat(run, 'reports')" />
          <ReportBrowser v-if="m.reportBrowser" :name="m.reportBrowser.run" :files="m.reportBrowser.files" :initial-view="m.reportBrowser.view" :theme="theme" :review-disabled="busy || !connected" @review="startResultsReview" />
          <details v-if="m.agent_activity?.length" class="direct-team"><summary><UsersRound :size="16" />Team review</summary><div class="direct-team-grid"><article v-for="agent in m.agent_activity" :key="agent.id"><header><b>{{ agent.role }}</b><Check v-if="agent.status === 'completed'" :size="14" /><CircleAlert v-else :size="14" /></header><p>{{ agent.summary }}</p></article></div></details>
          <details v-if="m.trace?.length" class="direct-trace"><summary><CheckCheck />{{ m.trace.length }} activity steps</summary><p v-for="(step,i) in m.trace" :key="i"><Check v-if="step.status === 'completed'" /><CircleAlert v-else />{{ step.label || step.tool }}<span>{{ step.status }}</span></p></details>
          <div v-if="m.runs?.length" class="direct-run-list"><button v-for="r in m.runs" :key="r.name" @click="openEvidenceInChat(r.name, m.runIntent || 'reports')"><FileChartColumn /><span><b>{{ r.title || r.name }}</b><small>{{ r.people == null ? 'Saved experiment' : `${r.people} simulated participants` }}{{ r.decision ? ` · ${r.decision}` : '' }}</small></span><ChevronRight /></button></div>
          <RunAudienceCard v-if="m.audience_run" :name="m.audience_run" :theme="theme" />
          <div v-if="m.experiment_setup" class="direct-experiment"><ExperimentSetup embedded :initial-workflow="m.experiment_setup.workflow || ''" @workflow="(id) => { m.experiment_setup.workflow = id; persist() }" /></div>
          <BrowserObservation
            v-for="observation in m.browser_observations || []"
            :key="observation.session_id"
            :theme="theme"
            :observation="observation"
            :can-ask="!busy && answerMode !== 'note'"
            @ask="askAboutPage(observation)"
          />
          <ConnectedResult v-for="(result,i) in m.tool_results || []" :key="`tool-${i}`" :result="result" :theme="theme" />
          <ChatArtifact v-for="(a,i) in m.artifacts || []" :key="`${a.run}-${a.file}-${i}`" :name="a.run" :file="a.file" :path="a.path || []" :title="a.title || reportTitle(a.file)" :files="artifactFiles[a.run] || []" :theme="theme" />
          <RouterLink v-if="m.workflow_id" class="direct-plan" :to="`/workflows/${m.workflow_id}`"><FlaskConical /><span><b>Your test draft is ready</b><small>Review the audience, ideas and model usage before running.</small></span><ChevronRight /></RouterLink>
          <div v-if="m.suggestions?.length" class="direct-followups" role="group" aria-label="Suggested questions"><button v-for="s in m.suggestions" :key="s" type="button" :disabled="busy" @click="send(s)">{{ s }}</button></div>
          <div v-if="m.id === lastMessageId && m.role === 'assistant' && nextChips.length" class="direct-followups direct-next" role="group" aria-label="Suggested next steps">
            <span class="direct-next-label">Next steps</span>
            <button v-for="c in nextChips" :key="c.id" type="button" :disabled="busy" :title="c.cost === 'free' ? 'Free: answered from the saved run' : 'Uses model calls. You see the cost and approve it first.'" @click="useChip(c)">{{ c.label }}<small v-if="c.cost !== 'free'">asks first</small></button>
          </div>
          <div v-if="m.role === 'assistant' && (m.content || m.run_card || m.agent?.status !== 'working')" class="direct-message-actions" role="group" aria-label="Message actions"><button type="button" :aria-label="copiedMessage === m.id ? 'Response copied' : 'Copy response'" :title="copiedMessage === m.id ? 'Copied' : 'Copy response'" :disabled="!m.content" @click="copyMessage(m)"><Check v-if="copiedMessage === m.id" :size="14" /><Copy v-else :size="14" /><span>{{ copiedMessage === m.id ? 'Copied' : 'Copy' }}</span></button><button v-if="m.id === lastMessageId && previousUser(m)" type="button" aria-label="Ask again" title="Ask again: sends your last message again" :disabled="busy" @click="retryAnswer(m)"><RotateCcw :size="14" /><span>Retry</span></button><button v-if="m.id === lastAssistantId" type="button" aria-label="Download this chat as Markdown" title="Download this chat as Markdown" @click="exportChat"><Download :size="14" /><span>Download chat</span></button></div>
          <div v-else-if="m.role === 'user' && !(m.author && m.author.id !== cloudAccount?.account.id)" class="direct-message-actions mine" role="group" aria-label="Your message actions"><button type="button" :aria-label="copiedMessage === m.id ? 'Message copied' : 'Copy message'" :title="copiedMessage === m.id ? 'Copied' : 'Copy'" @click="copyMessage(m)"><Check v-if="copiedMessage === m.id" :size="14" /><Copy v-else :size="14" /></button><button type="button" aria-label="Edit and send again" title="Edit and send again" @click="setDraft(String(m.content || ''))"><PencilLine :size="14" /></button></div>
          <div v-if="m.failed" class="direct-message-failure" role="status"><p><CircleAlert :size="14" />{{ m.error || 'This message did not receive an answer. Try again or choose another model.' }}</p><div v-if="messages.at(-1)?.id === m.id"><button class="direct-retry" :disabled="busy" @click="send(m.content, {retryId:m.id})"><RotateCcw :size="13" />Retry</button><button v-if="!m.previewUrl" class="direct-retry" :disabled="busy" @click="openModelPicker">Change model</button></div></div>
        </article>
        <section v-if="busy" class="direct-live" aria-label="Live request activity">
          <RequestActivity :events="liveEvents" :busy="busy" :mode="answerMode" />
          <BrowserObservation :theme="theme" v-for="observation in liveBrowsers" :key="observation.session_id" :observation="observation" />
          <ConnectedResult v-for="(result,i) in liveTools" :key="i" :result="result" :theme="theme" />
        </section>
      </div>
    </div>
    <div class="direct-bottom">
      <p v-if="cloudSyncError" class="direct-error" role="status">{{ cloudSyncError }}<button @click="retryCloudSync">Retry sync</button></p>
      <p v-if="error" class="direct-error" role="alert">{{ error }} <button v-if="/model|provider|spend|connection/i.test(error)" @click="settingsOpen = true">Settings</button><button @click="error = ''" aria-label="Dismiss error"><X /></button></p>
      <p v-if="uploading" class="direct-context" role="status"><LoaderCircle :size="15" />Reading your files…</p>
      <p v-if="retainedContext.omitted" class="direct-context-limit">{{ retainedContext.omitted }} sources do not fit within the 24,000-character context limit.</p>
      <div v-if="selectedRunReview" class="direct-context">
        <FileChartColumn :size="15" />
        <span>Reviewing {{ selectedRunReview.title }}</span>
        <button type="button" aria-label="Remove selected experiment" @click="selectedRunReview = null"><X /></button>
      </div>
      <div v-if="selectedPage && answerMode !== 'note'" class="direct-context">
        <Globe :size="15" />
        <span :title="selectedPage.url">Asking about {{ selectedPage.title || selectedPage.url }}</span>
        <button type="button" aria-label="Remove selected web page" @click="selectedPage = null"><X /></button>
      </div>
      <div v-if="context" class="direct-context"><FileText /><span>{{ context.name }}</span><button aria-label="Remove attached context" @click="context = null"><X /></button></div>
      <UploadedContext v-if="context?.files?.length" :files="context.files" :theme="theme" />
      <div class="direct-input-region" @keydown.capture="composerKey">
        <SkillPalette ref="skillPalette" :theme="theme" :open="skillsOpen" :query="draft" class="direct-skills" @select="pickFeature" @close="dismissSkills" />
        <div class="direct-composer-wrap">
        <LibraryComposer ref="composer" v-model="draft" :key="conversationId || 'new'" :busy="busy" :disabled="(!connected && answerMode !== 'note') || uploading" :models="modelOptions" :selected-model="selectedModel" :changing="modelsLoading" placeholder="Ask MarketMirror, or type / for tools…" @send="send" @stop="stop" @attach="fileInput?.click()" @connectors="connectionsTab = 'data'; connectionsOpen = true" @choose-run="runPicker?.openPicker()" @skills="openSkills" @browser="openWebPreview" @settings="settingsOpen = true" @model-change="changeModel" />
        <div class="direct-composer-options"><ChatModePicker v-model="answerMode" v-model:agents="teamAgents" v-model:agentModels="teamModels" :can-comment="!!cloudAccount" :models="modelOptions" :theme="theme" :disabled="busy" @use-brief="addTeamBrief" /><ChatToolPicker v-model="connectorTools" :theme="theme" :disabled="busy" @configure="router.push('/workspace/connectors')" /><RunContextPicker ref="runPicker" v-model="selectedRun" :runs="runs" :disabled="busy" :theme="theme" /></div>
        </div>
        <div v-if="pastedPage && connected && !busy && !uploading && answerMode !== 'note'" class="direct-web-shortcut">
          <Globe :size="15" aria-hidden="true" />
          <span>{{ pastedPage.hostname }}</span>
          <Button type="button" size="sm" variant="outline" @click="capturePastedPage">Preview website</Button>
        </div>
      </div>
        <div v-if="!messages.length" class="direct-starters" :class="{ four: homeStarters.length === 4 }">
          <button v-for="s in homeStarters" :key="s.title" @click="s.to ? router.push(s.to) : s.action ? selectFeature(s) : send(s.prompt)"><component :is="s.icon" /><span><b>{{ s.title }}</b><small>{{ s.text }}</small></span></button>
        </div>
        <section v-if="!messages.length && !activeProject && latestRun" class="dw-quick" aria-label="Quick looks at your latest experiment">
          <span class="dw-quick-label" :title="latestRun.title || latestRun.name">Latest: {{ displayTitle(latestRun.title || latestRun.name) }} <small>instant, free</small></span>
          <button v-for="q in quickLooks" :key="q.label" type="button" @click="openQuick(q)"><component :is="q.icon" :size="14" aria-hidden="true" />{{ q.label }}</button>
        </section>
        <section v-if="!messages.length && !activeProject && continueItems.length" class="dw-continue" aria-labelledby="dw-continue-title">
          <div class="dw-continue-head"><h2 id="dw-continue-title">Continue where you left off</h2></div>
          <div class="dw-continue-row">
            <RouterLink v-for="c in continueItems" :key="c.key" :to="c.to" class="dw-chat-card" :class="c.kind">
              <span class="dw-card-icon" aria-hidden="true"><component :is="c.kind === 'run' ? ChartNoAxesCombined : MessageSquare" :size="15" /></span>
              <span class="dw-card-body">
                <span class="dw-card-kind">{{ c.kind === 'run' ? 'Experiment' : 'Chat' }}<template v-if="c.when"> · {{ c.when }}</template></span>
                <b :title="c.title">{{ c.title }}</b>
                <small>{{ c.preview }}</small>
                <span class="dw-card-meta">
                  <span v-if="c.decision" class="dw-decision" :class="decisionTone(c.decision)">{{ decisionText(c.decision) }}</span>
                  <span v-for="x in c.meta" :key="x">{{ x }}</span>
                </span>
              </span>
            </RouterLink>
          </div>
        </section>

      <BrowserActivity v-model:open="browserActivityOpen" :captures="browserCaptures" :progress="browserProgress" :theme="theme" />
      <ChatConnections v-model:open="connectionsOpen" :initial-tab="connectionsTab" :theme="theme" :runs="runs" @attach="fileInput?.click()" @choose-run="runPicker?.openPicker()" @connected="loadModels" @configure-model="configureModel" />
      <ProjectKnowledge v-model:open="knowledgeOpen" :project="activeProject" :theme="theme" @updated="updateProjectContext" />
      <WorkspaceSettings v-model:open="settingsOpen" :initial-tab="settingsTab" :initial-provider="settingsProvider" :theme="theme" @models="openModelPicker" @saved="loadModels" />
      <Dialog v-model:open="projectPickerOpen"><DialogContent class="ws-overlay direct-project-dialog" :data-theme="theme"><DialogHeader><DialogTitle>{{ conversationId ? 'Move chat to a project' : 'Choose a project' }}</DialogTitle><DialogDescription>Project instructions will be available to this conversation.</DialogDescription></DialogHeader><input v-model="projectSearch" class="direct-project-search" type="search" placeholder="Search projects…" aria-label="Search projects" /><LoadingSkeleton v-if="projectPickerLoading" :lines="3" label="Loading projects" /><div v-else class="direct-project-choices" role="group" aria-label="Project choices"><button v-if="activeProject" :disabled="projectMoving" @click="moveToProject(null)"><FolderOpen :size="17" /><span><b>No project</b><small>Keep this chat outside a project</small></span></button><button v-for="project in matchingProjects" :key="project.id" :disabled="projectMoving" :aria-pressed="activeProject?.id === project.id" @click="moveToProject(project)"><FolderOpen :size="17" /><span><b>{{ project.name }}</b><small>{{ project.description || 'Project instructions and related chats' }}</small></span><Check v-if="activeProject?.id === project.id" :size="16" /></button><p v-if="!matchingProjects.length" class="direct-project-note">{{ projectSearch ? 'No matching projects.' : 'Create a project to organize your work.' }}</p></div><p v-if="projectPickerError" class="direct-error" role="alert">{{ projectPickerError }}</p><Button type="button" variant="outline" :disabled="projectMoving" @click="projectPickerOpen = false; createProject()">Create a new project</Button></DialogContent></Dialog>
      <Dialog v-model:open="projectOpen"><DialogContent class="ws-overlay direct-project-dialog" :data-theme="theme"><DialogHeader><DialogTitle>{{ editingProject ? 'Project details' : 'Create a project' }}</DialogTitle><DialogDescription>Keep related chats, research, and instructions together.</DialogDescription></DialogHeader><form class="direct-project-form" @submit.prevent="saveProject"><label>Project name<input v-model="projectForm.name" required maxlength="120" placeholder="For example, Summer campaign" /></label><label>Description<textarea v-model="projectForm.description" maxlength="2000" rows="2" placeholder="What is this project about?" /></label><label>Instructions<textarea v-model="projectForm.instructions" maxlength="12000" rows="4" placeholder="Audience, product context, constraints, and how MarketMirror should help…" /></label><p v-if="projectError" role="alert" class="direct-error">{{ projectError }}</p><div class="direct-project-actions"><Button type="button" variant="outline" @click="projectOpen = false">Cancel</Button><Button type="submit" :disabled="projectSaving">{{ projectSaving ? 'Saving…' : editingProject ? 'Save project' : 'Create project' }}</Button></div></form></DialogContent></Dialog>
      <Dialog v-model:open="webPreviewOpen">
        <DialogContent class="ws-overlay direct-project-dialog" :data-theme="theme">
          <DialogHeader>
            <DialogTitle>Preview a website</DialogTitle>
            <DialogDescription>Capture a public page and explore its content in this chat.</DialogDescription>
          </DialogHeader>
          <form class="direct-project-form" @submit.prevent="previewWebsite(false)">
            <label>Website URL<input v-model="webPreviewUrl" type="url" required placeholder="https://example.com" maxlength="2048" /></label>
            <p v-if="webPreviewError" class="direct-error" role="alert">{{ webPreviewError }}</p>
            <p class="direct-project-note">Preview captures the page. Analyze also uses the captured text to answer with your selected model or team.</p>
            <div class="direct-project-actions">
              <Button v-if="answerMode !== 'note'" type="button" variant="outline" :disabled="!webPreviewUrl.trim() || busy" @click="previewWebsite(true)">Analyze page</Button>
              <Button type="submit" :disabled="!webPreviewUrl.trim() || busy">Show preview</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <input ref="fileInput" type="file" accept=".pdf,.md,.txt,.csv,.json" multiple hidden @change="attach" />
    </div>
  </div>
</template>
<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { Sparkles, Lightbulb, UsersRound, ChartNoAxesCombined, FolderOpen, Paperclip, Database, FileText, Globe, X, FileChartColumn, ChevronRight, FlaskConical, LoaderCircle, CheckCheck, Check, CircleAlert, Copy, RotateCcw, Download, PencilLine, GitCompare, MessageSquare, MessagesSquare } from 'lucide-vue-next'
import MarketMirrorLogo from '../MarketMirrorLogo.vue'
import RunContextPicker from './RunContextPicker.vue'
import ChatToolPicker from './ChatToolPicker.vue'
import ChatModePicker from './ChatModePicker.vue'
import ConnectedResult from './ConnectedResult.vue'
import RequestActivity from './RequestActivity.vue'
import BrowserObservation from './BrowserObservation.vue'
import BrowserActivity from './BrowserActivity.vue'
const RunAudienceCard = defineAsyncComponent(() => import('./RunAudienceCard.vue'))
const RunChatCard = defineAsyncComponent(() => import('./RunChatCard.vue'))
import LoadingSkeleton from './LoadingSkeleton.vue'
const CompareRuns = defineAsyncComponent(() => import('./CompareRuns.vue'))
const ChatViewCard = defineAsyncComponent(() => import('./ChatViewCard.vue'))
const ExperimentSetup = defineAsyncComponent(() => import('../../views/Home.vue'))
import ChatConnections from './ChatConnections.vue'
import SkillPalette from './SkillPalette.vue'
import WorkspaceSettings from './WorkspaceSettings.vue'
import ProjectKnowledge from './ProjectKnowledge.vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog'
import { Button } from '../ui/button'
import { featureCatalog } from '../../workspace/featureCatalog'
import LibraryComposer from './LibraryComposer.vue'
import MarkdownText from './MarkdownText.vue'
import ChatArtifact from './ChatArtifact.vue'
import AgentTurn from './agent/AgentTurn.vue' // [agent-chat]
import { agentBody, agentChatEnabled, agentReply, markAnswered, runAgentTurn } from './agent/agentTurn.js' // [agent-chat]
import UploadedContext from './UploadedContext.vue'
import ReportBrowser from './ReportBrowser.vue'
import { resultsReview } from '../../workspace/teamReview'
import { buildConversationContext } from '../../workspace/conversationContext'
import TeamPresence from './TeamPresence.vue'
import { cloudAccount, cloudSyncError, retryCloudSync, postTeamNote } from '../../workspace/cloud'
import { streamChat } from '../../workspace/chatStream'
import { api, authHeaders, token } from '../../workspace/api.js'
import { chatFilename } from '../../workspace/chatFilename.js'
import { useChatCopyFeedback } from '../../workspace/chatCopyFeedback.js'
import { canEdit, signedIn } from '../../workspace/account.js'
import { reportTitle, savedReportFor } from '../../workspace/resultRouting.js'
import { CHAT_VIEWS, localViewIntent, slashView, splitSlash, viewIntro, viewTab } from '../../workspace/chatViews.js'
import { evidencePrompt, localRunIntent, messageRun, nextStepChips, objectionAnswer, runCardIntro, segmentAnswer, shownChips, tabForView } from '../../workspace/runCard.js'
import { continueEntries, decisionText, decisionTone, displayTitle, evidenceTitle, findEvidenceChat, isCompareRequest, pickCompareRuns, shortText as shortTitle } from '../../workspace/compareRuns.js'
import { plural } from '../../workspace/plural.js'
const props = defineProps({ runs: { type: Array, default: () => [] }, provider: { type: Object, default: () => ({}) }, theme: { default: 'light' } })
const route = useRoute(), router = useRouter(), messages = ref([]), conversationId = ref(''), busy = ref(false), error = ref(''), selectedRun = ref(''), artifactFiles = ref({}), scrollArea = ref(null), context = ref(null), fileInput = ref(null), uploading = ref(false)
watch(busy, value => window.dispatchEvent(new CustomEvent('mm-chat-status', { detail: { id: conversationId.value, status: value ? 'working' : 'idle' } })))
const connected = computed(() => !!token() || (signedIn.value && canEdit.value)), settingsLink = computed(() => `/setup#t=${encodeURIComponent(token())}`)
const connectionsTab = ref('data')
const composer = ref(null), runPicker = ref(null), connectionsOpen = ref(false), modelOptions = ref([]), selectedModel = ref(''), modelsLoading = ref(false)
const selectedPage = ref(null)
const selectedRunReview = ref(null)
const { copiedMessage, copyMessage } = useChatCopyFeedback(() => {
  error.value = 'Could not copy this response. Select the text to copy it.'
})
const retainedContext = computed(() => buildConversationContext(messages.value, context.value, undefined, selectedPage.value))
const lastAssistantId = computed(() => [...messages.value].reverse().find((m) => m.role === 'assistant')?.id)
const lastMessageId = computed(() => messages.value.at(-1)?.id)
// saved run details (files and summary) for the next-step chips; the run card fills this when it loads
const runDetails = ref({})
function rememberRun(detail) { if (detail?.name) runDetails.value[detail.name] = detail }
const chipRun = computed(() => {
  const last = messages.value.at(-1)
  if (busy.value || last?.role !== 'assistant' || last.failed) return ''
  return messageRun(last) || (last.agent && last.agent.status !== 'working' ? selectedRun.value : '')
})
watch(chipRun, async (name) => {
  if (!name || runDetails.value[name]) return
  try { rememberRun(await api(`/api/runs/${encodeURIComponent(name)}`)) } catch { /* no chips for a run that cannot be read */ }
}, { immediate: true })
const nextChips = computed(() => {
  const name = chipRun.value, detail = runDetails.value[name]
  if (!name || !detail) return []
  return nextStepChips({ run: name, title: detail.title || props.runs.find((r) => r.name === name)?.title || name, runs: props.runs, files: detail.files || [], summary: detail.summary, exclude: shownChips(messages.value.at(-1)) })
})
function useChip(chip) {
  if (busy.value || !chip) return
  if (chip.kind === 'compare') { compareInChat(chip.run, chip.other); return }
  selectedRun.value = chip.run
  send(chip.prompt, { chip })
}
// actions from an in-chat run card: asking people and focus groups go to the chat agent, which shows the cost
// on the approval card before anything runs; comparing is read from saved files
function runCardAction({ type, run, other, title, person, prompt, panel, feature } = {}) {
  // from a workspace view card shown by the agent: open a full panel, use a skill, or open a run
  if (type === 'open-panel') { openPanel(panel); return }
  if (type === 'feature' && feature) { selectFeature(feature); return }
  if (type === 'open-run' && run) { openEvidenceInChat(run, 'results'); return }
  if (busy.value || !run) return
  const label = shortTitle(displayTitle(title || runLabel(run)), 48)
  if (type === 'compare') { compareInChat(run, other); return }
  selectedRun.value = run
  // a person picked in the People tab: the draft names them; nothing is sent until the user presses send
  if (type === 'ask' && person?.id != null) setDraft(`Ask ${person.name || 'the simulated person'} (simulated person ${person.id}) from ${label}: `)
  else if (type === 'ask') setDraft(`Ask one of the simulated buyers from ${label}: `)
  else if (type === 'focus') send(`Run a focus group with simulated buyers from ${label}. Show me the cost before anything runs.`, { chip: { kind: 'agent' } })
  // landing analysis: testing a fix goes to the agent, which asks for approval before it spends; a new test only fills the box
  else if (type === 'agent-prompt' && prompt) send(prompt, { chip: { kind: 'agent' } })
  else if (type === 'draft' && prompt) setDraft(prompt)
}
async function compareInChat(a, b) {
  if (!a || !b || busy.value) return
  if (!conversationId.value) { conversationId.value = uid(); await router.replace({ path: route.path, query: { chat: conversationId.value, ...(activeProject.value ? { project: activeProject.value.id } : {}) } }) }
  messages.value.push({ id: uid(), role: 'user', content: `Compare ${shortTitle(runLabel(a), 48)} with ${shortTitle(runLabel(b), 48)}` })
  messages.value.push({ id: uid(), role: 'assistant', content: compareContent(a, b), compare: { a, b } })
  persist(); scrollBottom()
}
function previousUser(m) {
  const i = messages.value.findIndex((x) => x.id === m.id)
  for (let j = i - 1; j >= 0; j--) if (messages.value[j].role === 'user') return messages.value[j].kind === 'comment' ? null : messages.value[j]
  return null
}
// "Retry" drops the last answer and sends the message before it again (the same user bubble, no duplicate)
function retryAnswer(m) {
  const user = previousUser(m)
  if (busy.value || !user) return
  messages.value.splice(messages.value.indexOf(user) + 1)
  persist()
  send(user.content, { retryId: user.id })
}
function exportChat() {
  const title = stored().find((c) => c.id === conversationId.value)?.title || messages.value.find((m) => m.role === 'user')?.content?.slice(0, 80) || 'MarketMirror chat'
  const lines = [`# ${title}`, '', '_Answers about simulated buyers are simulated. Check decisions with real people before you spend._', '']
  for (const m of messages.value) if (m.content) lines.push(`**${m.role === 'user' ? 'You' : 'MarketMirror'}**`, '', String(m.content), '')
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: chatFilename(String(title)) })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}
const webPreviewOpen = ref(false), webPreviewUrl = ref(''), webPreviewError = ref('')
function webAddress(value) {
 const input = value.trim()
 if (input.length > 2048 || !/^https?:\/\/[^\s<>"`]+$/i.test(input)) return null
 try {
  const url = new URL(input)
  return !url.username && !url.password && url.href.length <= 2048 ? url : null
 } catch { return null }
}
function openWebPreview() {
 webPreviewUrl.value = pastedPage.value?.href || ''
 webPreviewError.value = ''
 webPreviewOpen.value = true
}
function previewWebsite(analyze) {
 if (busy.value) return
 const url = webAddress(webPreviewUrl.value)
 if (!url) { webPreviewError.value = 'Enter a complete HTTP or HTTPS link without a username or password.'; return }
 webPreviewOpen.value = false
 if (analyze) {
  send(`Analyze this website: ${url.href}`, { inspectUrl: url.href })
 } else {
  send(`Preview this website: ${url.href}`, { previewUrl: url.href })
 }
}
function capturePastedPage() {
 const url = pastedPage.value
 if (!url || busy.value) return
 send(`Preview this website: ${url.href}`, { previewUrl: url.href, clearDraft: true })
}
function askAboutPage(page) {
 selectedRunReview.value = null
 selectedPage.value = page
 setDraft(draft.value.trim() && !pastedPage.value ? draft.value : 'Summarize this page.')
}
const liveEvents = ref([]), liveBrowsers = ref([]), liveTools = ref([])
const browserActivityOpen = ref(false)
const browserCaptures = computed(() => {
 const captures = [...(busy.value ? [...liveBrowsers.value].reverse() : []),
  ...[...messages.value].reverse().flatMap(message => [...(message.browser_observations || [])].reverse())]
 const unique = new Map()
 for (const page of captures) {
  if (page?.session_id && !unique.has(page.session_id)) unique.set(page.session_id, page)
 }
 return [...unique.values()]
})
const browserProgress = computed(() => {
 if (!busy.value) return ''
 return liveEvents.value.findLast(event => event.tool === 'browse_page')?.label || ''
})
function requestProgress(event, ownTicket) {
 if (ownTicket !== ticket) return
 liveEvents.value.push(event)
 if (event.type === 'tool' && event.status === 'completed' && event.data) {
  if (event.tool === 'browse_page') liveBrowsers.value.push(event.data)
  if (event.tool === 'connector_tool') liveTools.value.push(event.data)
 }
 if (scrollArea.value && scrollArea.value.scrollHeight - scrollArea.value.scrollTop - scrollArea.value.clientHeight < 100) scrollBottom()
}
const teamAgents = ref(['market-analyst','critical-reviewer']), teamModels = ref({})
const answerMode = ref('standard')
watch(answerMode, mode => { if (mode !== 'team') selectedRunReview.value = null })
const connectorTools = ref(null), settingsTab = ref('models'), settingsProvider = ref('')
function configureModel(provider) { connectionsOpen.value = false; settingsTab.value = 'models'; settingsProvider.value = provider || ''; settingsOpen.value = true }
const draft = ref(''), skillPalette = ref(null), skillsDismissed = ref(false), settingsOpen = ref(false)
const pastedPage = computed(() => webAddress(draft.value))
const skillsOpen = computed(() => !busy.value && !skillsDismissed.value && draft.value.startsWith('/') && !draft.value.includes('\n'))
const knowledgeOpen = ref(false)
function updateProjectContext(project) { activeProject.value = project; window.dispatchEvent(new Event('mm-projects-updated')) }
const activeProject = ref(null), projectOpen = ref(false), editingProject = ref(false), projectSaving = ref(false), projectError = ref('')
const projectForm = ref({ name: '', description: '', instructions: '' })
const projectPickerOpen = ref(false), projectPickerLoading = ref(false), projectMoving = ref(false), projectPickerError = ref(''), projectSearch = ref(''), availableProjects = ref([])
const matchingProjects = computed(() => availableProjects.value.filter(project => `${project.name} ${project.description}`.toLowerCase().includes(projectSearch.value.trim().toLowerCase())))
async function openProjectPicker() {
 projectPickerOpen.value = true; projectSearch.value = ''; projectPickerError.value = ''; projectPickerLoading.value = true
 try { availableProjects.value = await api('/api/workspace/projects') } catch (err) { projectPickerError.value = err.message } finally { projectPickerLoading.value = false }
}
async function moveToProject(target) {
 if (projectMoving.value) return
 if (target?.id === activeProject.value?.id) { projectPickerOpen.value = false; return }
 projectMoving.value = true; projectPickerError.value = ''
 let previous = null, previousChanged = false
 try {
  if (conversationId.value && activeProject.value) {
   previous = await api(`/api/workspace/projects/${encodeURIComponent(activeProject.value.id)}`)
   await api(`/api/workspace/projects/${encodeURIComponent(previous.id)}`, { method: 'PATCH', body: { chat_ids: (previous.chat_ids || []).filter(id => id !== conversationId.value) } }); previousChanged = true
  }
  if (conversationId.value && target) {
   const current = await api(`/api/workspace/projects/${encodeURIComponent(target.id)}`)
   target = await api(`/api/workspace/projects/${encodeURIComponent(target.id)}`, { method: 'PATCH', body: { chat_ids: [...new Set([...(current.chat_ids || []), conversationId.value])], run_names: [...new Set([...(current.run_names || []), ...(selectedRun.value ? [selectedRun.value] : [])])] } })
  }
  activeProject.value = target; persist()
  const query = { ...route.query }; delete query.project; if (target) query.project = target.id
  await router.replace({ path: route.path, query }); window.dispatchEvent(new Event('mm-projects-updated')); projectPickerOpen.value = false
 } catch (err) {
  if (previousChanged) { try { await api(`/api/workspace/projects/${encodeURIComponent(previous.id)}`, { method: 'PATCH', body: { chat_ids: previous.chat_ids || [] } }) } catch { /* The error remains visible so the user can retry the association. */ } }
  projectPickerError.value = err.message
 } finally { projectMoving.value = false }
}
async function moveChatEvent(event) {
 const id = event.detail?.chatId || event.detail?.id || (typeof event.detail === 'string' ? event.detail : '')
 if (id && id !== conversationId.value) {
  const chat = stored().find(item => item.id === id)
  if (!chat) { error.value = 'This chat is no longer available in this browser.'; return }
  await router.push({ path: '/', query: { chat: id, ...(chat.project ? { project: chat.project } : {}) } }); await nextTick(); await loadProject()
 }
 openProjectPicker()
}
watch(draft, () => { skillsDismissed.value = false })
function setDraft(value) { draft.value = value; composer.value?.setValue(value); nextTick(() => composer.value?.focus()) }
function startResultsReview(experiment) {
 if (busy.value) return
 selectedRunReview.value = experiment
 selectedPage.value = null
 answerMode.value = 'team'
 teamAgents.value = [...resultsReview.roles]
 teamModels.value = Object.fromEntries(Object.entries(teamModels.value).filter(([role]) => resultsReview.roles.includes(role)))
 addTeamBrief(resultsReview.prompt)
}
function addTeamBrief(brief) {
 const current = draft.value.trim()
 setDraft(current.includes(brief) ? current : [brief, current].filter(Boolean).join('\n\n'))
}
function openSkills() { skillsDismissed.value = false; setDraft('/') }
function dismissSkills() { skillsDismissed.value = true }
function composerKey(event) { if (skillPalette.value?.handleKey(event)) event.stopPropagation() }
async function openModelPicker() { await loadModels(); await nextTick(); if (modelOptions.value.length) document.querySelector('.library-composer .an-model-trigger')?.click(); else connectionsOpen.value = true }
// from the / menu: "/people Kenya" keeps the words after the command as the view's filters
function pickFeature(feature) {
  const slash = splitSlash(draft.value)
  const typed = slash && (feature.command === slash.command || feature.aliases?.some(alias => `/${alias}` === slash.command))
  selectFeature(feature, typed && feature.view ? slash.rest : '')
}
function selectFeature(feature, rest = '') {
  setDraft(''); skillsDismissed.value = true
  if (feature.view) showView(slashView(feature.view, rest, { runs: props.runs, run: selectedRun.value }), rest ? `${feature.command} ${rest}` : feature.command)
  else if (feature.action === 'settings') settingsOpen.value = true
  else if (feature.action === 'connectors') connectionsOpen.value = true
  else if (feature.action === 'models') openModelPicker()
  else if (feature.action === 'project') createProject()
  else if (feature.action === 'analyze') openWebPreview()
  else if (feature.action === 'experiment') startExperiment()
  else if (feature.action === 'runs') send('Show my saved runs and reports.')
  else setDraft(feature.prompt)
}
// The full Settings or Connections panel, from a view card's link (their internals stay on their own pages).
function openPanel(panel) {
  if (panel === 'connectors') router.push('/workspace/connectors')
  else if (panel === 'settings' || panel === 'spending') { settingsTab.value = panel === 'spending' ? 'spending' : 'models'; settingsProvider.value = ''; settingsOpen.value = true }
}
// Everything from the chat: a view (any page, tab or panel of the app) as an assistant message, read from saved files
// with no model call. Run views become the run card at the matching tab with the filters; workspace views their card.
function viewMessage(spec) {
  const base = { id: uid(), role: 'assistant' }
  if (!spec || spec.needsRun) return { ...base, content: 'There are no saved runs yet, so there is nothing to show. Tell me about your product and the decision you want to test.' }
  const kind = CHAT_VIEWS[spec.view]?.kind
  if (kind === 'run') {
    selectedRun.value = spec.run
    const tab = viewTab(spec.view)
    return { ...base, content: viewIntro(spec, runLabel(spec.run)), run_card: { run: spec.run, tab, ...(spec.filters ? { filters: spec.filters } : {}), ...(spec.filters?.verdict ? { verdict: spec.filters.verdict } : {}) } }
  }
  if (kind === 'compare') {
    if (props.runs.length < 2) return { ...base, content: props.runs.length ? 'There is only one saved experiment so far. Run a second one, then compare them.' : 'There are no saved experiments to compare yet.' }
    const picks = spec.runs ? { a: spec.runs[0], b: spec.runs[1] } : pickCompareRuns('compare my last two experiments', props.runs, selectedRun.value)
    return { ...base, content: compareContent(picks.a, picks.b), compare: picks }
  }
  return { ...base, content: viewIntro(spec), view_card: spec }
}
// a slash command or a view card link: your words, then the view, in this chat
async function showView(spec, label) {
  if (busy.value || !spec) return
  if (!conversationId.value) { conversationId.value = uid(); await router.replace({ path: route.path, query: { chat: conversationId.value, ...(activeProject.value ? { project: activeProject.value.id } : {}) } }) }
  messages.value.push({ id: uid(), role: 'user', content: label || CHAT_VIEWS[spec.view]?.label || spec.view })
  messages.value.push(viewMessage(spec))
  persist(); scrollBottom()
}
// /workspace/skills links a view as ?open=<command id>
watch(() => route.query.open, async (id) => {
  if (typeof id !== 'string' || !id) return
  const feature = featureCatalog.find((item) => item.id === id)
  const query = { ...route.query }; delete query.open
  await router.replace({ path: route.path, query })
  if (feature) { await nextTick(); selectFeature(feature) }
}, { immediate: true })
// A new experiment is set up inside the conversation, as one step of the chat, not on a separate page.
async function startExperiment() {
  if (!conversationId.value) {
    conversationId.value = uid()
    await router.replace({ path: route.path, query: { chat: conversationId.value, ...(activeProject.value ? { project: activeProject.value.id } : {}) } })
  }
  messages.value.push({ id: uid(), role: 'user', content: 'Set up a new experiment' })
  messages.value.push({ id: uid(), role: 'assistant', content: 'Let’s set it up here. Pick what you are deciding, describe your product and the two ideas to compare, then review the plan. Nothing that costs money runs until you approve it, and every answer comes from simulated buyers.', experiment_setup: { workflow: '' } })
  persist()
  scrollBottom()
}
async function handleRouteAction() {
 const action = route.query.action
 if (typeof action !== 'string') return
 const feature = featureCatalog.find(item => item.action === action)
 if (!feature) return
 const query = { ...route.query }; delete query.action
 await router.replace({ path: route.path, query })
 await nextTick(); selectFeature(feature)
}
watch(() => route.query.action, () => handleRouteAction())
function createProject() { editingProject.value = false; projectForm.value = { name: '', description: '', instructions: '' }; projectError.value = ''; projectOpen.value = true }
function editProject() { if (!activeProject.value) return; editingProject.value = true; projectForm.value = { name: activeProject.value.name, description: activeProject.value.description, instructions: activeProject.value.instructions }; projectError.value = ''; projectOpen.value = true }
async function loadProject() {
 const id = route.query.project || stored().find(chat => chat.id === route.query.chat)?.project
 if (!id) { activeProject.value = null; return }
 try { const project = await api(`/api/workspace/projects/${encodeURIComponent(id)}`); if ((route.query.project || stored().find(chat => chat.id === route.query.chat)?.project) === id) { activeProject.value = project; const chat = stored().find(row => row.id === route.query.chat); if (project.preferred_model && !chat?.model) selectedModel.value = resolveModel(project.preferred_model) } }
 catch (err) { activeProject.value = null; error.value = err.message }
}
watch(() => [route.query.project, route.query.chat], loadProject)
async function associateProject() {
 if (!activeProject.value || !conversationId.value) return
 const chats = [...new Set([...(activeProject.value.chat_ids || []), conversationId.value])]
 const names = [...new Set([...(activeProject.value.run_names || []), ...(selectedRun.value ? [selectedRun.value] : [])])]
 activeProject.value = await api(`/api/workspace/projects/${encodeURIComponent(activeProject.value.id)}`, { method: 'PATCH', body: { chat_ids: chats, run_names: names } })
 window.dispatchEvent(new Event('mm-projects-updated'))
}
async function saveProject() {
 projectSaving.value = true; projectError.value = ''
 try {
  const path = editingProject.value ? `/api/workspace/projects/${encodeURIComponent(activeProject.value.id)}` : '/api/workspace/projects'
  const body = { ...projectForm.value, ...(!editingProject.value ? { chat_ids: conversationId.value ? [conversationId.value] : [], run_names: selectedRun.value ? [selectedRun.value] : [] } : {}) }
  activeProject.value = await api(path, { method: editingProject.value ? 'PATCH' : 'POST', body })
  projectOpen.value = false; persist(); window.dispatchEvent(new Event('mm-projects-updated'))
  await router.replace({ path: route.path, query: { ...(conversationId.value ? { chat: conversationId.value } : {}), project: activeProject.value.id } })
 } catch (err) { projectError.value = err.message } finally { projectSaving.value = false }
}
let defaultModelId = null
function resolveModel(id) {
 if (defaultModelId === null) return id
 const available = modelOptions.value.filter(model => model.available !== false)
 return (available.find(model => model.id === id) || available.find(model => model.id === defaultModelId) || available[0])?.id || ''
}
async function loadModels() {
 if (!connected.value) return
 modelsLoading.value = true
 try { if (['localhost','127.0.0.1','[::1]'].includes(location.hostname)) { try { await api('/api/workspace/local-models') } catch { /* Local discovery is optional; configured cloud models remain available. */ } } const data = await api('/api/workspace/models'); modelOptions.value = (data.models || []).map(m => ({...m,name:m.name === 'claude' ? 'Claude (default)' : m.name})); defaultModelId = data.default_id || ''; selectedModel.value = resolveModel(selectedModel.value) }
 catch(e) { error.value = e.message } finally { modelsLoading.value = false }
}
function changeModel(id) { const model = modelOptions.value.find(m => m.id === id); if (busy.value || !model) return; if (model.available === false) { connectionsTab.value = 'models'; connectionsOpen.value = true; return } selectedModel.value = id; persist() }
onMounted(() => { loadRecent(); window.addEventListener('mm-chats-updated', loadRecent); loadModels(); loadProject(); handleRouteAction(); if (route.query.connectors === '1') connectionsOpen.value = true; window.addEventListener('mm-create-project', createProject); window.addEventListener('mm-open-settings', openSettings); window.addEventListener('mm-move-chat', moveChatEvent) })
function openSettings() { settingsOpen.value = true }
function refreshSharedChat() { if (busy.value || !conversationId.value) return; const chat = stored().find(row => row.id === conversationId.value); if (chat) { messages.value = chat.messages || []; loadArtifacts() } }
window.addEventListener('mm-chats-loaded', refreshSharedChat)
watch(() => route.query.connectors, value => { if (value === '1') connectionsOpen.value = true })
// The Connections page sends "add a file" here: open the file picker once, then drop the flag from the address.
async function attachFromRoute() { if (route.query.attach !== '1') return; const query = { ...route.query }; delete query.attach; await router.replace({ path: route.path, query }); await nextTick(); fileInput.value?.click() }
watch(() => route.query.attach, attachFromRoute)
onMounted(attachFromRoute)
// Drop the query when the dialog closes, so the sidebar link stops looking
// active and can open the dialog again.
watch(connectionsOpen, open => {
  if (open || route.query.connectors !== '1') return
  const query = { ...route.query }
  delete query.connectors
  router.replace({ query })
})
watch(() => route.query.skill, async id => { if (typeof id !== 'string' || !id) return; const skill = featureCatalog.find(item => item.skillId === id); if (skill) { await nextTick(); setDraft(skill.prompt) } }, { immediate: true })
watch(() => route.query.prompt, async value => { if (typeof value === 'string') { await nextTick(); composer.value?.setValue(value); composer.value?.focus() } }, { immediate: true })
const STORE = 'mm-conversations-v1'
let controller = null, ticket = 0
const starters = [
 { title: 'New experiment', text: 'Choose a test and set it up', icon: Lightbulb, action: 'experiment' },
 { title: 'Explore my audience', text: 'People, responses and 3D views', icon: UsersRound, prompt: 'Show my saved runs so I can explore the simulated audience.' },
 { title: 'Understand the results', text: 'Charts and reports in this chat', icon: ChartNoAxesCombined, prompt: 'Show my saved reports and help me choose a result to explore.' },
]
const greeting = (() => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' })()
const latestRun = computed(() => props.runs[0] || null)
const homeStarters = computed(() => props.runs.length > 1
  ? [...starters, { title: 'Compare experiments', text: 'Two runs side by side', icon: GitCompare, prompt: 'Compare my last two experiments' }]
  : starters)
// these three are answered from the saved run in this browser, without a model call
const quickLooks = [
  { label: 'World map of the audience', icon: Globe, show: 'audience' },
  { label: 'Social feed', icon: MessagesSquare, show: 'feed' },
  { label: 'All reports', icon: FileText, show: 'reports' }
]
function openQuick(q) {
  if (!latestRun.value) return
  openEvidenceInChat(latestRun.value.name, q.show)
}
const ago = (t) => {
  if (!t) return ''
  const sec = (Date.now() - t) / 1000
  return sec < 3600 ? `${Math.max(1, Math.floor(sec / 60))} min ago` : sec < 86400 ? `${Math.floor(sec / 3600)} h ago` : new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
const recentChats = ref([])
function loadRecent() {
  recentChats.value = stored().filter((c) => Array.isArray(c.messages) && c.messages.length).map((c) => {
    const last = [...c.messages].reverse().find((m) => m.content) || {}
    return { id: c.id, project: c.project, run: c.run, messages: c.messages, title: c.title, when: ago(c.updated), preview: `${last.role === 'user' ? 'You' : 'MarketMirror'}: ${String(last.content || '').replace(/[*#_`>]/g, '').slice(0, 110)}` }
  })
}
// recent chats (one per title and run) first; the last slot is kept for the newest experiment without a chat
const continueItems = computed(() => continueEntries(recentChats.value, props.runs, 3).map(({ kind, chat: c, run: r }) => {
  if (kind === 'chat') {
    const title = c.title || 'New chat'
    const runName = c.run ? shortTitle(displayTitle(props.runs.find((x) => x.name === c.run)?.title || c.run), 28) : ''
    return {
      key: `c-${c.id}`, kind, title, when: c.when, preview: c.preview,
      meta: runName && !title.includes(runName.replace(/…$/, '')) ? [runName] : [],
      to: { path: '/', query: { chat: c.id, ...(c.project ? { project: c.project } : {}) } }
    }
  }
  const when = r.updated_at ? new Date(r.updated_at).getTime() : r.mtime ? r.mtime * 1000 : 0
  return {
    key: `r-${r.name}`, kind, title: r.title || r.name, when: when ? ago(when) : '', decision: r.decision,
    preview: r.summary ? String(r.summary).slice(0, 110) : 'Open its reports, audience and recorded activity.',
    meta: r.people ? [`${Number(r.people).toLocaleString()} simulated people`] : [],
    to: { path: '/', query: { run: r.name, show: 'reports' } }
  }
}))
// chats opened from saved evidence are titled "<View> · <short run title>"
function evidenceChatTitle() {
 const first = messages.value[0]
 if (first?.role !== 'user' || !first.evidenceRun || !first.evidenceView) return ''
 return evidenceTitle(first.evidenceView, props.runs.find(r => r.name === first.evidenceRun)?.title || first.evidenceRun)
}
const runLabel = (name) => displayTitle(props.runs.find(r => r.name === name)?.title || name)
function compareContent(a, b) {
 return a && b
  ? `Here are **${runLabel(a)}** (A) and **${runLabel(b)}** (B) side by side, read from your saved runs without a model call. Every number is simulated: read which way a difference points, not its size.`
  : 'Choose two saved experiments to compare. Every number is simulated.'
}
// changing a pick in the embedded comparison updates this message and the saved chat
function updateCompare(message, picks) {
 message.compare = { a: picks.a || '', b: picks.b || '' }
 message.content = compareContent(message.compare.a, message.compare.b)
 persist()
}
const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
function stored() { try { const value = JSON.parse(localStorage.getItem(STORE) || '[]'); return Array.isArray(value) ? value : [] } catch { return [] } }
function persist() {
 if (!conversationId.value || !messages.value.length) return
 try {
  const previous = stored().find(c => c.id === conversationId.value)
  const chats = stored().filter(c => c.id !== conversationId.value)
  chats.unshift({ id: conversationId.value, customTitle: previous?.customTitle, title: previous?.customTitle || evidenceChatTitle() || messages.value.find(m => m.role === 'user')?.content.slice(0, 80) || 'New chat', connectorTools: connectorTools.value, answerMode: answerMode.value, teamAgents: teamAgents.value, teamModels: teamModels.value, updated: Date.now(), messages: messages.value, run: selectedRun.value, model: selectedModel.value, project: activeProject.value?.id || null })
  localStorage.setItem(STORE, JSON.stringify(chats))
  window.dispatchEvent(new Event('mm-chats-updated'))
 } catch { error.value = 'This browser could not save chat history. You can keep chatting in this session.' }
}
async function loadArtifacts() {
 const names = [...new Set(messages.value.flatMap(m => m.artifacts || []).map(a => a.run))]
 await Promise.all(names.map(async name => { if (artifactFiles.value[name]) return; try { const d = await api(`/api/runs/${encodeURIComponent(name)}`); artifactFiles.value[name] = d.files || [] } catch { artifactFiles.value[name] = [] } }))
}
function openConversation() {
 if (route.query.chat && route.query.chat === conversationId.value) return
 ticket++; controller?.abort(); busy.value = false; error.value = ''; context.value = null; draft.value = ''; skillsDismissed.value = false
 selectedPage.value = null
 selectedRunReview.value = null
 webPreviewOpen.value = false
 browserActivityOpen.value = false
 const chat = stored().find(c => c.id === route.query.chat)
 teamAgents.value = Array.isArray(chat?.teamAgents) ? chat.teamAgents : ['market-analyst','critical-reviewer']; teamModels.value = chat?.teamModels && typeof chat.teamModels === 'object' ? chat.teamModels : {}
 answerMode.value = ['team', ...(cloudAccount.value ? ['note'] : [])].includes(chat?.answerMode) ? chat.answerMode : 'standard'
 connectorTools.value = Array.isArray(chat?.connectorTools) ? chat.connectorTools : null
 conversationId.value = chat?.id || ''; messages.value = Array.isArray(chat?.messages) ? chat.messages : []; selectedRun.value = chat?.run || ''; selectedModel.value = resolveModel(chat?.model || selectedModel.value)
 loadArtifacts(); scrollBottom()
}
watch(() => [route.query.chat, route.query.new], openConversation, { immediate: true })
async function scrollBottom() { await nextTick(); if (scrollArea.value) scrollArea.value.scrollTop = messages.value.length ? scrollArea.value.scrollHeight : 0 }
async function send(text, options = {}) {
 text = typeof text === 'string' ? text.trim() : ''
 if (!text || busy.value) return
 const analyzeCommand = /^\/(?:analyze|browser|web-analysis)\s+(.+)$/s.exec(text)
 if (analyzeCommand && !options.retryId && answerMode.value !== 'note') {
  const url = webAddress(analyzeCommand[1])
  if (!url) {
   webPreviewUrl.value = analyzeCommand[1]
   webPreviewError.value = 'Enter a complete HTTP or HTTPS link.'
   webPreviewOpen.value = true
   return
  }
  text = `Analyze this website: ${url.href}`
  options = { ...options, inspectUrl: url.href }
 }
 if (text.startsWith('/')) {
  const slash = splitSlash(text)
  const named = (command) => featureCatalog.find(item => item.command === command || item.aliases?.some(alias => `/${alias}` === command))
  // "/people kenya": a view with filters; other commands only match on their own
  const viewFeature = slash?.rest && named(slash.command)?.view ? named(slash.command) : null
  if (viewFeature) { selectFeature(viewFeature, slash.rest); return }
  const feature = named(text)
  if (feature) { selectFeature(feature); return }
 }
 const retried = options.retryId ? messages.value.at(-1) : null
 if (options.retryId && (retried?.id !== options.retryId || retried.role !== 'user')) return
 const previewUrl = retried?.previewUrl || options.previewUrl
 const inspectUrl = retried?.inspectUrl || options.inspectUrl
 const evidenceRun = retried?.evidenceRun || options.evidenceRun
 // an explicit agent action (a card button or chip) goes to the agent flow whatever the answer mode, never a note or team answer
 const explicitAgent = options.chip?.kind === 'agent'
 const pinnedReview = answerMode.value === 'team' && !explicitAgent && !previewUrl && !inspectUrl && !evidenceRun
  ? selectedRunReview.value : null
 const reviewRun = retried ? retried.reviewRun : pinnedReview?.name
 const runName = evidenceRun || reviewRun || selectedRun.value || (!options.chip && localRunIntent(text) ? props.runs[0]?.name || '' : '')
 const teamNote = !explicitAgent && !previewUrl && !inspectUrl && !evidenceRun && !retried && answerMode.value === 'note' && cloudAccount.value
 if (!connected.value && !teamNote) { error.value = signedIn.value && !canEdit.value ? 'You can read this workspace. Ask an owner to make you an editor to start conversations.' : 'Connect your local workspace before starting a conversation.'; return }
 if (text.length > 12000) { error.value = 'Keep your message under 12,000 characters. Use Add context for a document.'; return }
 if (route.query.project && activeProject.value?.id !== route.query.project) { await loadProject(); if (!activeProject.value) return }
 if (!conversationId.value) { conversationId.value = uid(); await router.replace({ path: route.path, query: { chat: conversationId.value, ...(activeProject.value ? { project: activeProject.value.id } : {}) } }) }
 if (evidenceRun) selectedRun.value = evidenceRun
 if (teamNote) {
  busy.value = true; error.value = ''; liveEvents.value = []; liveBrowsers.value = []; liveTools.value = []
  try { const chat = await postTeamNote(conversationId.value,text); messages.value = chat.messages; try { await associateProject() } catch { error.value = 'Note shared. Project association could not be updated.' } persist(); scrollBottom() }
  catch (err) { error.value = err.message; setDraft(text) }
  finally { busy.value = false }
  return
 }
 const ownTicket = ++ticket
 const page = retried
  ? messages.value.flatMap(message => message.browser_observations || []).find(item => item.session_id === retried.pageId)
  : !previewUrl && !inspectUrl && !evidenceRun && !reviewRun ? selectedPage.value : null
 const userMessage = retried || {
  id: uid(), role: 'user', content: text,
  ...(cloudAccount.value ? { author: { id: cloudAccount.value.account.id, email: cloudAccount.value.account.email } } : {}),
  ...(previewUrl ? { previewUrl } : {}),
  ...(inspectUrl ? { inspectUrl } : {}),
  ...(evidenceRun ? { evidenceRun } : {}),
  ...(evidenceRun && options.evidenceView ? { evidenceView: options.evidenceView } : {}),
  ...(reviewRun ? { reviewRun } : {}),
  ...(page ? { pageId: page.session_id } : {}),
  ...(!previewUrl && context.value?.files?.length ? { attachedFiles: context.value.files.map(file => ({ name: file.name, text: file.text })) } : {})
 }
 userMessage.failed = false; delete userMessage.error
 if (!retried) messages.value.push(userMessage)
 if (options.clearDraft) draft.value = ''
 busy.value = true; error.value = ''; liveEvents.value = []; liveBrowsers.value = []; liveTools.value = []; persist(); scrollBottom()
 controller = new AbortController()
 try {
  await associateProject()
  if (ownTicket !== ticket) return
  if (previewUrl) {
   liveEvents.value.push({type:'tool',tool:'browse_page',status:'working',label:'Opening the website'})
   const observation = await api('/api/workspace/browser/observe',{method:'POST',body:{url:previewUrl},signal:controller.signal})
   if (ownTicket !== ticket) return
   messages.value.push({ id: uid(), role: 'assistant', content: 'Here is the captured page.', browser_observations: [observation] })
   return
  }
  // Comparing two saved runs is read from their files, without a provider call.
  if (!page && !inspectUrl && !reviewRun && !evidenceRun && isCompareRequest(text, props.runs)) {
   if (props.runs.length < 2) {
    messages.value.push({ id: uid(), role: 'assistant', content: props.runs.length ? 'There is only one saved experiment so far. Run a second one, then ask me to compare them.' : 'There are no saved experiments to compare yet. Tell me about your product and the decision you want to test.' })
    return
   }
   const picks = pickCompareRuns(text, props.runs, selectedRun.value)
   messages.value.push({ id: uid(), role: 'assistant', content: compareContent(picks.a, picks.b), compare: picks })
   return
  }
  // Common free requests ("show the people in Kenya", "what's my spend") open the view from saved files, no model call.
  if (!page && !inspectUrl && !reviewRun && !evidenceRun && options.chip?.kind !== 'agent') {
   const view = localViewIntent(text, { runs: props.runs, run: selectedRun.value })
   if (view) { messages.value.push(viewMessage(view)); return }
  }
  // Opening saved evidence is deterministic and does not need a provider call.
  if (!page && !runName && /show (my )?(saved )?(runs|reports)|show my saved runs/i.test(text)) {
   messages.value.push({ id: uid(), role: 'assistant', content: props.runs.length ? 'Choose a saved experiment to explore its reports, persona profiles and recorded activity. You can also select a run below and ask for a specific chart here.' : 'There are no saved experiments yet. Tell me about your product and the decision you want to test.', runIntent: /audience|people|persona|world|globe/i.test(text) ? 'audience' : 'reports', runs: props.runs.map(r => ({ name:r.name,title:r.title,people:r.people,decision:r.decision })) }); return
  }
  // chips and card actions that need the chat agent (they spend, after approval) skip the saved-file shortcuts
  if (!page && !inspectUrl && !reviewRun && runName && options.chip?.kind !== 'agent') {
   const d = await api(`/api/runs/${encodeURIComponent(runName)}`, { signal: controller.signal })
   if (ownTicket !== ticket) return
   artifactFiles.value[runName] = d.files || []
   rememberRun(d)
   const runTitle = d.title || props.runs.find(r => r.name === runName)?.title || runName
   // a saved view opened from the sidebar, the home page or a link: the run card, at the matching tab
   if (evidenceRun) {
    const tab = tabForView(userMessage.evidenceView)
    messages.value.push({ id: uid(), role: 'assistant', content: runCardIntro(tab, runTitle), run_card: { run: runName, tab } })
    return
   }
   // near-exact questions and "show ..." about the selected run are answered from its saved files
   const intent = options.chip?.kind === 'agent' ? null : localRunIntent(text)
   if (intent) {
    const content = intent.kind === 'objections' ? objectionAnswer(d.summary) : intent.kind === 'segments' ? segmentAnswer(d.summary) : runCardIntro(intent.tab, runTitle)
    messages.value.push({ id: uid(), role: 'assistant', content, run_card: { run: runName, tab: intent.tab, ...(intent.verdict ? { verdict: intent.verdict } : {}), ...(intent.kind === 'segments' ? { focus: 'segments' } : {}) } })
    return
   }
   if (/\b(3d|world|globe|audience|personas|map|people)\b/i.test(text) && /show|view|explore|visual|map|3d|world|globe/i.test(text)) {
    messages.value.push({ id: uid(), role: 'assistant', content: runCardIntro('market', runTitle), run_card: { run: runName, tab: 'market' } }); return
   }
   if (/^(show|open|explore|view) (the )?(social feed|social conversations|social activity)\b/i.test(text)) {
    messages.value.push({ id: uid(), role: 'assistant', content: runCardIntro('feed', runTitle), run_card: { run: runName, tab: 'feed' } })
    return
   }
   if (/show\s+(all|every).*report|all results|every section|^(show|open|explore|view) (the )?(run |report )?highlights\b/i.test(text)) {
    messages.value.push({ id: uid(), role: 'assistant', content: runCardIntro('results', runTitle), run_card: { run: runName, tab: 'results' } })
    return
   }
   const saved = savedReportFor(text, d.files, d.summary)
   if (saved && /show|chart|report|visual|pricing|funnel|analyst|action plan|\.json|\.csv|\.md/i.test(text)) {
    messages.value.push({ id: uid(), role: 'assistant', content: `Here are the saved ${saved.title.toLowerCase()} results. Explore the fields below or select a numeric column to visualize it.`, artifacts: [{run:runName,...saved}] }); return
   }
  }
  // [agent-chat] standard chat goes to the chat agent: the MCP server's tools with the same spend approval
  if (agentChatEnabled() && (answerMode.value === 'standard' || explicitAgent) && !reviewRun && !inspectUrl && !page) { await sendToAgent({ ownTicket, runName }); return }
  const history = []
  let remaining = 44000
  for (const m of [...messages.value].reverse()) {
    const content = history.length && m.content.length > 9500 ? m.content.slice(0, 9400) + '\n[Earlier message shortened for conversation context.]' : m.content
    if (content.length > remaining) break
    history.unshift({ role:m.role,content:m.kind === 'comment' ? '[Team note] ' + content : content }); remaining -= content.length
    if (history.length >= 25) break
  }
  const fileContext = buildConversationContext(messages.value, context.value, undefined, page)
  const sourceName = page ? `Selected saved page: ${page.url}`.slice(0, 200) : fileContext.name
  const mode = reviewRun || (answerMode.value === 'team' && !explicitAgent) ? 'team' : 'standard'
  const payload = {
   messages: history,
   mode,
   ...(mode === 'team' ? { team_agents: teamAgents.value, team_models: teamModels.value } : {}),
   ...(connectorTools.value !== null ? { connector_tools: connectorTools.value } : {}),
   ...(activeProject.value ? { project: activeProject.value.id } : {}),
   ...(selectedModel.value ? { model: selectedModel.value } : {}),
   ...(fileContext.files.length ? { context: { name: sourceName, text: fileContext.text } } : {}),
   ...(runName ? { run: runName } : {}),
   ...(reviewRun ? { review_summary: true } : {}),
   ...(inspectUrl ? { inspect_url: inspectUrl } : {})
  }
  const response = await streamChat(payload, { signal: controller.signal, onEvent: event => requestProgress(event, ownTicket) })
  if (ownTicket !== ticket) return
  messages.value.push({ id:uid(),role:'assistant',content:response.message,artifacts:response.artifacts || [],trace:response.trace || [],suggestions:response.suggestions || [],tool_results:response.tool_results || [],browser_observations:response.browser_observations || [],agent_activity:response.agent_activity || [],workflow_id:response.workflow_id })
  await loadArtifacts(); context.value = null
  if (selectedPage.value?.session_id === page?.session_id) selectedPage.value = null
  if (reviewRun && selectedRunReview.value?.name === reviewRun) selectedRunReview.value = null
 } catch(e) { if (ownTicket === ticket) { userMessage.failed = true; userMessage.error = e.name === 'AbortError' ? 'Stopped waiting for this response.' : e.message === 'Failed to fetch' ? 'The connection was interrupted. Try again.' : e.message; error.value = '' } }
 finally { if (ownTicket === ticket) { busy.value = false; persist(); scrollBottom() } }
}
// [agent-chat] begin: one agent turn into a new assistant message; approvals resume the paused turn on the server
async function sendToAgent({ ownTicket, runName, resume = null }) {
 messages.value.push(agentReply(uid())); const live = messages.value.at(-1)
 const files = !resume && context.value?.files?.length ? context.value.files.map(f => ({ name: f.name, text: f.text })) : []
 const body = agentBody({ sessionId: conversationId.value, messages: messages.value, model: selectedModel.value, run: runName, project: activeProject.value?.id, files, resume })
 const done = await runAgentTurn({ message: live, body, signal: controller.signal, onChange: () => { if (ownTicket === ticket) scrollBottom() } })
 if (done && !resume) context.value = null
}
async function resumeAgent(m, { pendingId, answer, label }) {
 if (busy.value || !conversationId.value) return
 markAnswered(m.agent, pendingId, label)
 const ownTicket = ++ticket; busy.value = true; error.value = ''; controller = new AbortController(); persist()
 try { await sendToAgent({ ownTicket, runName: selectedRun.value, resume: { id: pendingId, answer } }) }
 finally { if (ownTicket === ticket) { busy.value = false; persist(); scrollBottom() } }
}
function agentAction(id) { if (id === 'use_claude_code_login') { connectionsTab.value = 'models'; connectionsOpen.value = true } else settingsOpen.value = true }
// [agent-chat] end
function stop() { const latest = messages.value.at(-1); if (busy.value && latest?.role === 'user') { latest.failed = true; latest.error = 'Stopped waiting for this response.' } ticket++; controller?.abort(); busy.value = false; persist() }
async function attach(event) {
 const files = [...(event.target.files || [])]; if (!files.length) return
 if (files.some(file => file.size > 5 * 1024 * 1024)) { error.value = 'Choose documents smaller than 5 MB each.'; event.target.value = ''; return }
 uploading.value = true; error.value = ''
 try {
  const pieces = context.value?.files ? [...context.value.files] : context.value ? [{ name: context.value.name, text: context.value.text }] : []
  for (const file of files) {
   if (/\.(csv|json)$/i.test(file.name)) {
    const text = await file.text(); if (text.length > 24000) throw new Error(`${file.name} exceeds 24,000 characters. Use a smaller export.`)
    if (file.name.toLowerCase().endsWith('.json')) JSON.parse(text)
    pieces.push({name:file.name,text})
   } else {
    const form = new FormData(); form.append('file', file)
    const response = await fetch('/api/workflows/source', { method:'POST',headers:authHeaders(),body:form })
    const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.error || `Could not read ${file.name}.`)
    pieces.push({name:file.name,text:data.data.text})
   }
  }
  const text = pieces.map(piece => `## ${piece.name}\n${piece.text}`).join('\n\n')
  if (text.length > 24000) throw new Error('The combined context exceeds 24,000 characters. Choose fewer files or smaller exports.')
  context.value = { name: pieces.map(piece => piece.name).join(', '), text, files: pieces }
 } catch(e) { error.value = e.message }
 finally { uploading.value = false; event.target.value = '' }
}
let openingEvidence = false
const evidenceViews = { results: 'Reports', reports: 'Reports', audience: 'Audience', market: 'Audience', world_map: 'Audience', feed: 'Social feed', social_feed: 'Social feed', thinking: 'Buyer responses', activity: 'Activity' }
async function openEvidenceInChat(name, show = 'reports') {
 if (busy.value || openingEvidence) return
 openingEvidence = true
 try {
  const prompt = evidencePrompt(show)
  // from the home page, reopen the chat that already shows this evidence instead of starting another one
  if (!conversationId.value) {
   const existing = findEvidenceChat(stored(), name, prompt)
   if (existing) {
    await router.replace({ path: route.path, query: { chat: existing.id, ...(existing.project ? { project: existing.project } : {}) } })
    return
   }
  }
  await send(prompt, { evidenceRun: name, evidenceView: evidenceViews[show] || evidenceViews[tabForView(show)] || 'Reports' })
 } catch (err) { error.value = err.message } finally { openingEvidence = false }
}
watch(() => [route.query.run, route.query.show], async ([name, show]) => {
 if (typeof name !== 'string' || !name || openingEvidence) return
 await nextTick(); await openEvidenceInChat(name, typeof show === 'string' ? show : 'reports')
 const query = { ...route.query }; delete query.run; delete query.show
 await router.replace({path:route.path,query})
}, { immediate: true })
onBeforeUnmount(() => { window.removeEventListener('mm-chats-updated', loadRecent); window.dispatchEvent(new CustomEvent('mm-chat-status', {detail:{id:conversationId.value,status:'idle'}})); ticket++; controller?.abort(); window.removeEventListener('mm-chats-loaded', refreshSharedChat); window.removeEventListener('mm-create-project', createProject); window.removeEventListener('mm-open-settings', openSettings); window.removeEventListener('mm-move-chat', moveChatEvent) })
</script>
<style scoped>
.direct-project-toolbar{display:flex;gap:14px;align-items:center;width:min(100%,var(--chat-width));padding:8px 28px 0;margin:0 auto}.direct-project-toolbar button{display:flex;align-items:center;gap:7px;border:0;background:none;color:var(--muted);font-size:11px;padding:5px 0;cursor:pointer}.direct-project-toolbar button:first-child{min-width:0;max-width:75%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.direct-project-toolbar button+button{margin-left:auto}.direct-project-search{padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel-2);color:var(--text);font-size:13px;outline-offset:3px}.direct-project-search:focus-visible{outline:2px solid var(--accent)}.direct-project-choices{display:grid;gap:7px;max-height:340px;overflow:auto}.direct-project-choices button{display:flex;align-items:center;gap:11px;width:100%;padding:13px;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--text);text-align:left;cursor:pointer}.direct-project-choices button:hover,.direct-project-choices button[aria-pressed=true]{background:var(--panel-2);border-color:var(--accent)}.direct-project-choices button>span{flex:1;min-width:0}.direct-project-choices b{display:block;font-size:12px;font-weight:550}.direct-project-choices small{display:block;margin-top:4px;color:var(--muted);font-size:11px;line-height:1.6;white-space:nowrap;text-overflow:ellipsis;overflow:hidden}.direct-project-choices button:disabled{opacity:.6;cursor:wait}.direct-project-note{font-size:12px;line-height:1.7;color:var(--muted);padding:12px 0}
.direct-input-region{position:relative}.direct-skills{position:absolute;bottom:calc(100% + 10px);left:0;right:0;z-index:35}.direct-project-edit{margin-top:12px;padding:7px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);font-size:11px;color:var(--muted);cursor:pointer}:global(.direct-project-dialog){width:min(560px,calc(100vw - 32px));max-width:560px!important;max-height:90dvh;overflow:auto;background:var(--panel)!important;color:var(--text);border-color:var(--line)!important;border-radius:22px!important;padding:28px!important}:global(.direct-project-dialog [data-slot=dialog-description]){color:var(--muted);font-size:12px;line-height:1.7}.direct-project-form{display:grid;gap:18px;margin-top:8px}.direct-project-form label{display:flex;flex-direction:column;gap:8px;font-size:12px;font-weight:550}.direct-project-form input,.direct-project-form textarea{padding:11px 12px;background:var(--panel-2);border:1px solid var(--line);border-radius:10px;font:inherit;font-weight:400;color:var(--text);resize:vertical}.direct-project-form input:focus-visible,.direct-project-form textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.direct-project-actions{display:flex;justify-content:flex-end;gap:10px}.direct-project-actions button[type=submit]{background:var(--accent);color:white}
.direct-chat{height:calc(100dvh - 98px);min-height:540px;display:flex;flex-direction:column;--chat-width:800px}.direct-scroll{overflow:auto;flex:1;min-height:0;padding:25px 28px}.direct-welcome{max-width:740px;margin:clamp(30px,9vh,110px) auto 35px;text-align:center}.direct-symbol{width:56px;height:56px;display:grid;place-items:center;margin:0 auto 22px;border-radius:16px;color:var(--text)}.direct-symbol svg{width:40px;height:40px}.direct-welcome h1{font-size:30px;font-weight:550;letter-spacing:-1px;margin-bottom:14px}.direct-welcome>p{font-size:14px;line-height:1.8;color:var(--muted)}.direct-starters{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:35px auto 0;max-width:620px;text-align:left}.direct-starters button{display:flex;align-items:flex-start;gap:12px;padding:17px;background:var(--panel);border:1px solid var(--line);border-radius:10px;text-align:left;cursor:pointer}.direct-starters button:hover{background:var(--panel-2);border-color:var(--accent)}.direct-starters svg{width:18px;height:18px;color:var(--accent);flex-shrink:0;margin-top:2px}.direct-starters b{display:block;font-size:13px;font-weight:550}.direct-starters small{display:block;font-size:12px;color:var(--muted);margin-top:5px;line-height:1.5}.direct-bottom{width:min(100%,var(--chat-width));margin:0 auto;padding:10px 20px 16px}.direct-composer-wrap:focus-within{border-color:var(--accent)}.direct-composer-wrap{border:1px solid var(--line);padding-top:4px;border-radius:18px;background:var(--panel);box-shadow:0 4px 20px rgb(20 30 25 / 4%);overflow:hidden}.direct-composer-options{display:flex;align-items:center;gap:12px;padding:0 12px 10px;flex-wrap:wrap;border-top:1px solid var(--line)}.direct-scope-note{font-size:11px;color:var(--muted);margin-left:auto;padding-right:8px}.direct-composer-options button,.direct-composer-options label{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);background:none;border:0;cursor:pointer}.direct-composer-options select{max-width:180px;font-size:12px;border:0;background:var(--panel);color:var(--muted)}.direct-composer-options svg{width:14px;height:14px}.direct-model{margin-left:auto;font-size:11px;color:var(--muted);display:flex;gap:6px;align-items:center}.direct-model>span{width:5px;height:5px;background:var(--accent);border-radius:50%}.direct-footnote{font-size:11px;color:var(--muted);line-height:1.6;text-align:center;margin-top:10px}.direct-error{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:12px;border:1px solid var(--line);background:var(--panel-2);border-radius:8px;margin-bottom:10px;font-size:13px}.direct-error a{text-decoration:underline}.direct-error button,.direct-context button{background:none;border:0;margin-left:auto;cursor:pointer}.direct-error svg,.direct-context svg{width:15px;height:15px}.direct-context{display:flex;gap:8px;align-items:center;font-size:12px;padding:10px 3px}.direct-messages{width:min(100%,var(--chat-width));margin:0 auto}.direct-message{padding:15px 0 25px;font-size:14px;line-height:1.8;min-width:0}.direct-message.user{margin-left:15%;padding:15px 20px;border-radius:14px;background:var(--panel-2);margin-bottom:20px}.direct-message-label{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:550;margin-bottom:10px}.direct-mini-mark{width:25px;height:25px;color:var(--text);flex-shrink:0}.direct-message-text{white-space:pre-wrap;overflow-wrap:anywhere}.direct-run-list{display:flex;flex-direction:column;gap:6px;margin-top:15px}.direct-run-list a,.direct-run-list button,.direct-plan{display:flex;gap:12px;align-items:center;padding:14px;border:1px solid var(--line);border-radius:9px;font-size:13px}.direct-run-list a:hover,.direct-run-list button:hover,.direct-plan:hover{background:var(--panel-2)}.direct-run-list svg,.direct-plan svg{width:18px;height:18px;flex-shrink:0;color:var(--accent)}.direct-run-list a>svg:last-child,.direct-run-list button>svg:last-child,.direct-plan>svg:last-child{margin-left:auto}.direct-run-list b,.direct-plan b{display:block;font-weight:500}.direct-run-list small,.direct-plan small{display:block;color:var(--muted);margin-top:4px;font-size:12px}.direct-plan{margin-top:15px}.direct-trace{margin:12px 0;color:var(--muted);font-size:12px}.direct-trace summary{cursor:pointer;display:flex;gap:7px;align-items:center}.direct-trace svg{width:14px;height:14px}.direct-trace p{display:flex;align-items:center;gap:7px;margin:7px 0}.direct-trace p>span{margin-left:auto}.direct-followups{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.direct-followups button{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:12px;cursor:pointer}.direct-working{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;padding:10px 0 20px}.direct-working svg{width:16px;height:16px;animation:chat-spin 1.5s linear infinite}@keyframes chat-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.direct-working svg{animation:none}}@media(max-width:760px){.direct-chat{height:calc(100dvh - 84px);min-height:470px}.direct-scroll{padding:20px 16px}.direct-welcome{margin-top:30px}.direct-welcome h1{font-size:25px}.direct-starters{gap:8px;margin-top:25px}.direct-starters button{padding:12px;gap:8px}.direct-starters small{font-size:11px}.direct-bottom{padding:8px 12px 12px}.direct-composer-options{gap:9px}.direct-model{display:none}.direct-message.user{margin-left:7%}.direct-footnote{font-size:10px}}
@media(max-height:760px) and (min-width:761px){.direct-welcome{margin:4px auto 12px}.direct-symbol{width:36px;height:36px;margin-bottom:12px}.direct-symbol svg{width:32px;height:32px}.direct-welcome h1{font-size:26px;margin-bottom:8px}.direct-welcome>p{font-size:13px;line-height:1.6}.direct-starters{grid-template-columns:repeat(4,minmax(0,1fr));max-width:720px;margin-top:20px;gap:8px}.direct-starters button{padding:12px 10px;gap:8px;min-height:62px;align-items:center}.direct-starters b{font-size:12px}.direct-starters small{display:none}.direct-starters svg{width:16px;height:16px}.direct-scroll{padding-top:18px;padding-bottom:12px}}
.direct-chat:not(.started){justify-content:center;gap:22px;overflow-y:auto}.direct-chat:not(.started) .direct-scroll{flex:none;overflow:visible;padding:20px 28px 0}.direct-chat:not(.started) .direct-welcome{margin:0 auto;max-width:700px}.direct-chat:not(.started) .direct-bottom{padding-top:0}.direct-chat:not(.started) .direct-starters{grid-template-columns:repeat(3,minmax(0,1fr));max-width:none;margin-top:18px;gap:12px}.direct-chat:not(.started) .direct-starters button{min-height:100px;padding:18px 16px;align-items:flex-start;flex-direction:column;gap:12px}.direct-chat:not(.started) .direct-starters small{display:block;font-size:11px;line-height:1.6}.direct-chat:not(.started) .direct-starters b{font-size:13px}.direct-chat:not(.started) .direct-symbol{margin-bottom:16px}.direct-chat:not(.started) .direct-footnote{margin-top:16px}
@media(max-height:760px) and (min-width:761px){.direct-chat:not(.started){gap:14px}.direct-chat:not(.started) .direct-scroll{padding-top:12px}.direct-chat:not(.started) .direct-symbol{margin-bottom:10px}.direct-chat:not(.started) .direct-welcome>p br{display:none}.direct-chat:not(.started) .direct-starters button{min-height:84px;padding:12px;flex-direction:row;gap:10px}.direct-chat:not(.started) .direct-starters small{font-size:11px}.direct-chat:not(.started) .direct-footnote{font-size:10px;margin-top:10px}}
@media(max-width:600px){.direct-chat:not(.started){justify-content:flex-start;gap:20px;padding-top:20px}.direct-chat:not(.started) .direct-starters{grid-template-columns:minmax(0,1fr);gap:8px}.direct-chat:not(.started) .direct-starters button{min-height:64px;padding:12px 14px;flex-direction:row;gap:12px;align-items:center}.direct-chat:not(.started) .direct-bottom{padding-bottom:20px}.direct-scope-note{display:none}}
.direct-chat.started .direct-scroll{padding-top:20px;padding-bottom:24px;overscroll-behavior:contain;scroll-padding-bottom:28px}.direct-chat .direct-messages{display:flex;flex-direction:column;gap:24px;padding-bottom:12px}.direct-chat .direct-messages .direct-message{padding:0;margin:0;font-size:14px;line-height:1.75}.direct-chat .direct-messages .direct-message.user{width:fit-content;max-width:80%;align-self:flex-end;margin-left:auto;padding:11px 16px;border-radius:17px}.direct-chat .direct-messages .direct-message.assistant{width:100%}.direct-chat .direct-message-label{margin-bottom:10px;font-size:12px}.direct-chat .direct-message-actions{display:flex;align-items:center;gap:8px;margin-top:10px}.direct-message-actions button,.direct-retry{display:inline-flex;align-items:center;gap:6px;padding:5px;border:0;border-radius:6px;background:transparent;color:var(--muted);font-size:11px;cursor:pointer}.direct-message-actions button:hover{color:var(--text);background:var(--panel-2)}.direct-retry{padding:5px 0;margin-top:8px}.direct-retry:disabled{opacity:.5;cursor:wait}.direct-chat .direct-project-toolbar{width:min(calc(100% - 56px),var(--chat-width));padding:10px 0 0;margin:0 auto}.direct-chat .direct-project-toolbar button:first-child{max-width:70%;padding:6px 10px;border:1px solid var(--line);border-radius:20px;background:var(--panel);font-size:10px;line-height:15px}.direct-chat .direct-project-toolbar button+button{font-size:10px}.direct-chat .direct-bottom{flex-shrink:0}.direct-context-limit{font-size:10px;line-height:1.6;color:var(--muted);margin:0 0 8px}.direct-chat .direct-followups{gap:7px;margin-top:14px}.direct-chat .direct-followups button{font-size:11px;padding:7px 10px;line-height:1.5}.direct-chat .direct-project-edit+.direct-project-edit{margin-left:8px}@media(max-width:600px){.direct-chat .direct-project-toolbar{width:calc(100% - 32px);padding-top:8px}.direct-chat .direct-project-toolbar button+button{display:none}.direct-chat .direct-messages .direct-message.user{max-width:88%;padding:10px 13px}.direct-chat.started .direct-scroll{padding-bottom:24px}}
</style>

<style scoped>
.direct-web-shortcut {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding: 5px 6px 5px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--panel);
  color: var(--muted);
  font-size: 12px;
}
.direct-web-shortcut > svg { flex-shrink: 0; }
.direct-web-shortcut > span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.direct-web-shortcut > button { flex-shrink: 0; }
</style>

<style scoped>
.direct-team{margin-top:18px}.direct-team>summary{display:flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:var(--muted)}.direct-team-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}.direct-team-grid article{padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--panel);font-size:12px;line-height:1.6}.direct-team-grid header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}.direct-team-grid b{font-weight:550}.direct-team-grid p{color:var(--muted)}@media(max-width:700px){.direct-team-grid{grid-template-columns:1fr}}
</style>

<style scoped>
.direct-live{font-size:12px;color:var(--muted);min-width:0}.direct-live summary{cursor:pointer;padding:9px 0}.direct-live ol{list-style:none;padding:0;display:grid;gap:8px;margin:8px 0 14px}.direct-live li{display:flex;align-items:flex-start;gap:8px;line-height:1.6}.direct-live li svg{flex-shrink:0;margin-top:3px}.direct-live li small{display:block;margin-top:4px;white-space:pre-wrap}
</style>

<style scoped>.direct-run-list>button{width:100%;text-align:left;background:var(--panel);color:var(--text);cursor:pointer}.direct-run-list>button span{min-width:0}.direct-run-list>button b{overflow-wrap:anywhere}</style>

<style scoped>.direct-author{font-size:10px;color:var(--muted);line-height:1.6;margin-top:7px}.direct-chat .direct-messages .direct-message.user.other-member{align-self:flex-start;margin-left:0;margin-right:auto;background:var(--panel);border:1px solid var(--line)}</style>

<style scoped>.direct-message-failure{max-width:380px;margin-top:10px;border-top:1px solid var(--line);padding-top:10px}.direct-message-failure>p{display:flex;align-items:flex-start;gap:7px;font-size:12px;line-height:1.6;color:var(--muted)}.direct-message-failure>p svg{flex-shrink:0;margin-top:3px}.direct-message-failure>div{display:flex;gap:14px;margin-top:3px}.direct-message-failure .direct-retry{font-size:12px;line-height:1.4}
</style>

<style scoped>
.direct-chat .direct-project-toolbar > .direct-browser-toggle {
 display: inline-flex; flex-shrink: 0; align-items: center; gap: 5px; margin-inline-start: auto;
 padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); font-size: 11px;
}
.direct-chat .direct-project-toolbar > .direct-browser-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media(max-width:600px) { .direct-chat .direct-project-toolbar:has(.direct-browser-toggle) { gap: 8px; } }
</style>

<style scoped>
/* Chat home on a phone: starters in two columns with titles only, no subtitle under the heading */
@media (max-width: 600px) {
  .direct-chat:not(.started) .direct-starters,
  .direct-chat:not(.started) .direct-starters.four { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .direct-chat:not(.started) .direct-starters button { min-height: 56px; padding: 11px 12px; flex-direction: row; gap: 10px; align-items: center; }
  .direct-chat:not(.started) .direct-starters small { display: none; }
  .direct-chat:not(.started) .direct-welcome > p.dw-sub { display: none; }
}
</style>
