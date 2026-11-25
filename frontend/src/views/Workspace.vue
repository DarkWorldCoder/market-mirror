<template>
  <div class="ws" :data-theme="theme">
    <a class="ws-skip" href="#ws-content">Skip to content</a>
    <button v-if="menuOpen" class="ws-scrim" aria-label="Close navigation" @click="closeDrawer"></button>
    <nav id="ws-navigation" class="ws-side" :class="{ open: menuOpen }" :inert="isMobile && !menuOpen" aria-label="Workspace" @keydown="trapDrawerFocus">
      <RouterLink to="/" class="ws-brand" @click="menuOpen = false"><MarketMirrorLogo :size="30" /><span>MarketMirror</span></RouterLink>
      <button v-if="canEdit" class="ws-new-chat" @click="newChat"><Plus :size="17" />New chat</button>
      <div class="ws-search-sticky">
        <div class="ws-search">
          <Search :size="16" aria-hidden="true" />
          <input ref="searchBox" v-model="search" type="search" placeholder="Search projects, chats, runs and skills" aria-label="Search projects, chats and runs" aria-describedby="ws-search-count" @keydown="onSearchKeydown" />
          <button v-if="search" class="ws-clear-search" aria-label="Clear search" @click="search = ''; searchBox?.focus()"><X :size="14" /></button>
          <kbd v-else>{{ isMac ? '⌘ K' : 'Ctrl K' }}</kbd>
        </div>
      </div>
      <div class="ws-side-scroll" @keydown="onResultsKeydown">
        <div v-if="!search.trim()" class="ws-nav ws-primary-nav">
          <RouterLink to="/workspace" :class="{ active: view === 'dashboard' }" :aria-current="view === 'dashboard' ? 'page' : undefined" @click="menuOpen = false"><LayoutDashboard class="ico" />Overview</RouterLink>
          <RouterLink to="/workspace/reports" :class="{ active: view === 'reports' }" :aria-current="view === 'reports' ? 'page' : undefined" @click="menuOpen = false"><ChartNoAxesCombined class="ico" />Reports</RouterLink>
          <RouterLink to="/workspace/compare" :class="{ active: view === 'compare' }" :aria-current="view === 'compare' ? 'page' : undefined" @click="menuOpen = false"><GitCompare class="ico" />Compare</RouterLink>
          <RouterLink to="/workspace/skills" :class="{ active: view === 'skills' }" :aria-current="view === 'skills' ? 'page' : undefined" @click="menuOpen = false"><Shapes class="ico" />Skills</RouterLink>
          <RouterLink v-if="!signedIn" to="/workspace/connectors" :class="{ active: view === 'connectors' }" :aria-current="view === 'connectors' ? 'page' : undefined" @click="menuOpen = false"><Plug class="ico" />Connections</RouterLink>
        </div>
        <p v-else-if="searchResultCount" id="ws-search-count" class="ws-search-caption" role="status" aria-live="polite">{{ searchResultCount }} {{ searchResultCount === 1 ? 'result' : 'results' }}</p>
        <section v-if="!search.trim() || filteredProjects.length" class="ws-side-section" aria-label="Projects">
          <div class="ws-section-heading"><RouterLink to="/workspace/projects" :class="{ active: view === 'projects' }" :aria-current="view === 'projects' ? 'page' : undefined" @click="menuOpen = false">Projects</RouterLink><button v-if="canEdit" aria-label="Create project" title="Create project" @click="createProject"><Plus :size="15" /></button></div>
          <div class="ws-history">
            <RouterLink v-for="p in filteredProjects" :key="p.id" :to="{path:'/',query:{project:p.id}}" :class="{active: route.query.project === p.id}" :title="p.name" @click="menuOpen = false"><FolderOpen :size="14" /><span>{{ p.name }}</span></RouterLink>
            <p v-if="projectsError && !search.trim()" class="ws-side-empty" role="alert">{{ projectsError }} <button class="ws-retry" @click="loadProjects">Retry</button></p>
            <button v-else-if="!projects.length && !search.trim()" class="ws-empty-project" @click="createProject"><Plus :size="14" />Create your first project</button>
          </div>
        </section>
        <section v-if="!search.trim() && pinnedRuns.length" class="ws-side-section" aria-label="Pinned runs">
          <div class="ws-section-heading"><span>Pinned runs</span></div>
          <div class="ws-history"><div v-for="r in pinnedRuns" :key="r.name" class="ws-chat-row"><RouterLink :to="{path:'/',query:{run:r.name,show:'reports'}}" :class="{ active: route.params.run === r.name || currentChat?.run === r.name }" :title="r.title" @click="menuOpen = false"><Pin :size="14" /><span>{{ r.title }}</span></RouterLink><button class="ws-chat-move ws-pin-run" aria-pressed="true" :aria-label="`Unpin ${r.title}`" title="Unpin" @click="togglePin(r.name)"><PinOff :size="14" /></button></div></div>
        </section>
        <details v-if="!search.trim() || filteredChats.length" class="ws-side-section" open>
          <summary>Your chats<ChevronDown :size="13" /></summary>
          <div class="ws-history"><div v-for="c in filteredChats" :key="c.id" class="ws-chat-row"><form v-if="editingChat === c.id" class="ws-chat-inline-form" @submit.prevent="finishInlineRename"><input v-model="renameTitle" data-inline-chat-name aria-label="Rename chat" maxlength="120" @blur="finishInlineRename" @keydown.esc="editingChat = ''" /><span v-if="renameError" role="alert">{{ renameError }}</span></form><RouterLink v-else :to="{path:'/',query:{chat:c.id,...(c.project ? {project:c.project} : {})}}" :class="{active:route.query.chat === c.id}" :aria-current="route.query.chat === c.id ? 'page' : undefined" :title="c.title" @click="menuOpen = false"><MessageSquare :size="14" /><span>{{ c.title }}</span><LoaderCircle v-if="workingChats.has(c.id)" class="ws-chat-working" :size="13" aria-label="Response in progress" /><i v-else-if="route.query.chat === c.id" class="ws-current-chat-dot" aria-label="Current chat"></i></RouterLink><Popover v-if="canEdit" :open="activeChatMenu === c.id" @update:open="activeChatMenu = $event ? c.id : ''"><PopoverTrigger as-child><button class="ws-chat-move" :data-chat-menu="c.id" aria-haspopup="menu" :aria-expanded="activeChatMenu === c.id" :aria-label="`Actions for ${c.title}`" title="Chat actions" @keydown.down.prevent="openChatMenu(c)"><MoreHorizontal :size="15" /></button></PopoverTrigger><PopoverContent class="ws-overlay ws-chat-action-menu" :data-theme="theme" align="end" role="menu" aria-label="Chat actions" @keydown="onChatMenuKeydown"><button role="menuitem" @click="openRename(c)"><Pencil :size="14" />Rename chat</button><button role="menuitem" @click="moveChat(c.id)"><FolderOpen :size="14" />Move to project</button><button v-if="canEdit" role="menuitem" class="ws-chat-delete" @click="deleteChat(c)"><Trash2 :size="14" />Delete chat</button></PopoverContent></Popover></div><p v-if="!chats.length && !search.trim()" class="ws-side-empty">Your conversations appear here.</p></div>
        </details>
        <details v-if="!search.trim() || filteredRuns.length" class="ws-side-section" :open="!!search.trim()">
          <summary>Saved runs<ChevronDown :size="13" /></summary>
          <div class="ws-history"><div v-for="r in filteredRuns" :key="r.name"><RouterLink :to="{path:'/',query:{run:r.name,show:'reports'}}" :class="{ active: route.params.run === r.name || currentChat?.run === r.name }" :title="r.title" @click="menuOpen = false"><ChartNoAxesCombined :size="14" /><span>{{ r.title }}</span></RouterLink><button class="ws-chat-move ws-pin-run" :aria-pressed="pins.includes(r.name)" :aria-label="`${pins.includes(r.name) ? 'Unpin' : 'Pin'} ${r.title}`" :title="pins.includes(r.name) ? 'Unpin' : 'Pin to the top'" @click="togglePin(r.name)"><component :is="pins.includes(r.name) ? PinOff : Pin" :size="14" /></button><div v-if="route.params.run === r.name || currentChat?.run === r.name" class="ws-run-shortcuts"><RouterLink v-for="destination in runDestinations" :key="destination.view" :to="{path:'/',query:{run:r.name,show:destination.view}}" :class="{active:route.query.view === destination.view}" @click="menuOpen = false">{{ destination.label }}</RouterLink></div></div><p v-if="!runs.length && !search.trim()" class="ws-side-empty">{{ loaded ? 'No saved runs yet.' : 'Loading runs…' }}</p></div>
        </details>
        <section v-if="searchedSkills.length" class="ws-side-section" aria-label="Matching skills"><div class="ws-section-heading">Skills</div><div class="ws-history"><RouterLink v-for="skill in searchedSkills" :key="skill.id" :to="skillLink(skill)" @click="menuOpen = false"><Shapes :size="14" /><span>{{ skill.label }}</span></RouterLink></div></section>
        <div v-if="search.trim() && !searchResultCount" class="ws-search-none" role="status"><Search :size="18" aria-hidden="true" /><b>No matches for “{{ search.trim() }}”</b><span>Try a project, chat or report name.</span><button type="button" @click="search = ''; searchBox?.focus()">Clear search</button></div>
      </div>
      <div class="ws-foot ws-nav">
        <template v-if="cloudAccount"><a href="/team" @click="menuOpen = false"><UsersRound class="ico" />Team & workspaces</a><a href="/account" @click="menuOpen = false"><ShieldCheck class="ico" />{{ cloudAccount.account?.name || cloudAccount.account?.email || 'Your account' }}</a></template>
        <RouterLink v-else to="/workspace/team" :class="{ active: view === 'team' }" @click="menuOpen = false"><UsersRound class="ico" /><span class="ws-foot-workspace">{{ signedIn ? (accountState.workspace?.name || 'Workspace') : 'Workspace & team' }}<small v-if="signedIn">{{ accountState.account?.email }} · {{ role }}</small></span></RouterLink>
        <p v-if="syncStatus" class="ws-side-empty ws-sync" role="status">{{ syncStatus }} <button v-if="chatSyncState === 'offline'" class="ws-retry" @click="retryChatSync">Retry</button></p>
        <p v-if="signedIn && !canEdit" class="ws-side-empty">You can view this workspace. Ask an owner for edit access.</p>
        <button v-if="spendMeter && !signedIn" class="ws-spend-meter" @click="openSettings"><Wallet class="ico" /><span>Estimated spend {{ spendMeter }}<template v-if="spend.limit"> of {{ money(spend.limit) }}</template></span></button>
        <p v-if="signedIn" class="ws-side-empty">Engine settings belong to the computer running MarketMirror. Ask whoever set it up.</p>
        <button v-if="!signedIn" @click="openSettings"><Settings2 class="ico" />Settings</button>
        <button class="ws-theme-toggle" @click="toggleTheme"><component :is="theme === 'dark' ? Sun : Moon" class="ico" />{{ theme === 'dark' ? 'Light appearance' : 'Dark appearance' }}</button>
      </div>
    </nav>

    <main id="ws-content" class="ws-main" :inert="isMobile && menuOpen">
      <header class="ws-top">
        <div class="ws-crumbs">
          <button ref="menuButton" class="ws-btn ws-menu-btn" aria-label="Open navigation" aria-controls="ws-navigation" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen"><Menu :size="20" /></button>
          <div v-if="currentChat" class="ws-inline-title"><input :value="currentChat.title" class="ws-page-title ws-chat-title-input" aria-label="Chat name" maxlength="120" @change="renameInPlace(currentChat,$event)" @keydown.enter="$event.target.blur()" @keydown.esc="$event.target.value=currentChat.title; $event.target.blur()" /><span v-if="inlineRenameError" role="alert">{{ inlineRenameError }}</span></div><b v-else class="ws-page-title">{{ contextualTitle }}</b>
        </div>
        <div class="ws-top-actions"><button v-if="canEdit" class="ws-top-project" aria-label="Create project" @click="createProject"><Plus :size="15" /><span>New project</span></button><button v-if="!signedIn" class="ws-top-settings" aria-label="Open settings" title="Settings" @click="openSettings"><Settings2 :size="17" /></button></div>
      </header>
      <p v-if="error" class="ws-error" role="alert">{{ error }} <button class="ws-retry" @click="refresh">Retry</button></p>
      <p v-if="finishedToast" class="ws-toast" role="status"><b>{{ finishedToast.title }}</b> finished. <RouterLink :to="{path:'/',query:{run:finishedToast.name,show:'reports'}}" @click="finishedToast = null">Open</RouterLink><button v-if="canEnableNotifications" class="ws-retry" @click="enableRunNotifications">Enable browser notifications</button><button class="ws-retry" @click="finishedToast = null">Dismiss</button></p>

      <section class="ws-canvas">
        <WorkspaceOverview v-if="view === 'dashboard' || view === 'reports'" :runs="runs" :projects="projects" :mode="view" :provider="provider" :loading="!loaded" :theme="theme" @refresh="refresh" @select-run="openRun" />
        <RunView v-else-if="view === 'run'" :key="route.params.run" :name="route.params.run" :theme="theme" />

        <ChatWorkspace v-else-if="view === 'chat'" :runs="runs" :provider="provider" :theme="theme" />
        <ConnectionsPage v-else-if="view === 'connectors'" :runs="runs" :theme="theme" />
        <CompareRuns v-else-if="view === 'compare'" :runs="runs" :theme="theme" />
        <TeamPanel v-else-if="view === 'team'" />

        <div v-else-if="view === 'notfound'" class="ws-section" style="padding-top: 24px">
          <div class="ws-project-empty"><Compass :size="30" /><h2>This page does not exist</h2><p>The link may be old or mistyped. Pick up where you left off instead.</p><div class="ws-notfound-actions"><RouterLink class="ws-project-create" to="/">Go to chat</RouterLink><RouterLink class="ws-project-create" to="/workspace">Open overview</RouterLink></div></div>
        </div>

        <div v-else-if="view === 'projects'" class="ws-section" style="padding-top: 24px">
          <div class="ws-catalog-head"><div><h1>Projects</h1><p class="ws-note">Keep conversations, research and reports together.</p></div><button v-if="canEdit" class="ws-project-create" @click="createProject"><Plus :size="16" />New project</button></div>
          <div class="ws-project-empty" v-if="projectsError" role="alert"><FolderOpen :size="30" /><h2>Projects could not load</h2><p>Check the connection and try again. Nothing was deleted.</p><button class="ws-project-create" @click="loadProjects">Retry</button></div>
          <div v-else class="ws-cards"><RouterLink v-for="p in filteredProjects" :key="p.id" class="ws-card ws-project-card" :to="{path:'/',query:{project:p.id}}"><FolderOpen :size="23" /><b>{{ p.name }}</b><span>{{ p.description || 'Open this project to continue your work.' }}</span></RouterLink></div>
          <div v-if="!projects.length && !projectsError" class="ws-project-empty"><FolderOpen :size="30" /><h2>A space for each idea</h2><p>Start a project to organize your conversations and findings.</p><button v-if="canEdit" class="ws-project-create" @click="createProject"><Plus :size="16" />Create a project</button><p v-else class="ws-note">You can view this workspace. Ask an owner for edit access.</p></div>
        </div>

        <div v-else-if="view === 'skills'" class="ws-section ws-skills-page" style="padding-top: 24px">
          <div class="ws-catalog-head"><div><h1>Tools for every decision</h1><p class="ws-note">{{ skills.length }} skills, from product research to a real-world check. Type / in chat to find them anytime.</p></div><button v-if="canManageSkills" class="ws-project-create" @click="openCustomSkill()"><Plus :size="15" />Add skill</button></div>
          <p v-if="customSkillError" class="ws-error" role="alert">Custom skills could not load. <button @click="reloadCustomSkills">Retry</button></p>
          <label class="ws-catalog-search"><Search aria-hidden="true" /><input v-model="skillSearch" type="search" placeholder="Find a skill: pricing, website, forecast…" aria-label="Find a skill" /></label>
          <div class="ws-skill-navigation" role="group" aria-label="Skill categories"><button :aria-pressed="skillCategory === 'all'" @click="skillCategory = 'all'">All skills <span>{{ skills.length }}</span></button><button v-for="group in featureGroups" :key="group" :aria-pressed="skillCategory === group" @click="skillCategory = group"><component :is="categoryIcons[group] || Shapes" :size="14" />{{ group }}<span>{{ skills.filter(skill => skill.group === group).length }}</span></button></div>
          <p class="ws-note" style="margin-bottom: 20px">Open saved evidence, configure your workspace, or prepare a request in chat. Model-backed experiments use your configured provider.</p>
          <template v-for="(group, groupIndex) in matchingSkillGroups" :key="group"><div class="ws-skill-group-heading"><h2 class="ws-skill-group">{{ group }}</h2><p>{{ categoryDescriptions[group] }}</p></div><div class="ws-cards">
            <div v-for="s in filteredSkills.filter(skill => skill.group === group)" :key="s.id" class="ws-skill-card-wrap"><RouterLink class="ws-card ws-skill-card" :to="skillLink(s)" :style="{ '--tint': skillTints[featureGroups.indexOf(group) % skillTints.length] }">
              <span class="ws-ico"><component :is="skillIcons[s.id] || categoryIcons[group] || Shapes" :size="21" /></span><b>{{ s.label }}</b>
              <span>{{ s.description }}</span>
              <span class="ws-skill-card-footer"><span>{{ s.command }}</span><ArrowUpRight :size="15" /></span>
            </RouterLink><a v-if="s.custom && s.sourceUrl" class="ws-skill-source" :href="s.sourceUrl" target="_blank" rel="noopener noreferrer" :aria-label="`Source for ${s.label}`">Source</a><button v-if="s.custom && canManageSkills" class="ws-skill-edit" :aria-label="`Edit ${s.label}`" title="Edit skill" @click="openCustomSkill(s)"><Pencil :size="14" /></button></div>
          </div></template>
          <div v-if="!filteredSkills.length" class="ws-skill-empty"><Search :size="25" /><h2>No matching skills</h2><p>Try a broader search or choose another category.</p><button @click="skillSearch = ''; skillCategory = 'all'">Show all skills</button></div>
          <p class="ws-note">{{ 'Chat helps you plan the test and explore its evidence. Execution options depend on the selected skill.' }}</p>
        </div>


      </section>
    </main>
    <CustomSkillDialog v-model:open="customSkillOpen" :skill="customSkillEditing" :theme="theme" />
    <OnboardingDialog v-model:open="onboardingOpen" :theme="theme" :latest-run="runs[0]?.name || ''" @settings="onboardingOpen = false; openSettings()" />
    <Dialog v-model:open="shortcutsOpen">
      <DialogContent class="ws-overlay ws-shortcuts" :data-theme="theme">
        <DialogHeader><DialogTitle>Keyboard shortcuts</DialogTitle><DialogDescription>Work without the mouse.</DialogDescription></DialogHeader>
        <dl class="ws-shortcut-list"><div v-for="k in shortcuts" :key="k.what"><dt><kbd v-for="x in k.keys" :key="x">{{ x }}</kbd></dt><dd>{{ k.what }}</dd></div></dl>
      </DialogContent>
    </Dialog>

  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { LoaderCircle, MoreHorizontal, Pencil, Brain, Cpu, Database, FileText, Globe, Mail, FlaskConical, Lightbulb, Target, Image, Camera, ClipboardList, ShieldCheck, Scale, Wallet, Network, Mic, Tag, Route, Workflow, GitCompare, Layers, Clock, BookOpen, ArrowUpRight, UsersRound, Megaphone, Compass, Sparkles, LayoutDashboard, MessageSquare, ChartNoAxesCombined, FolderOpen, Shapes, Plug, Split, Plus, Search, X, ChevronDown, Settings2, Sun, Moon, Menu, Trash2 } from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '../components/ui/popover'
import { featureCatalog, featureGroups, searchFeatures, loadCustomSkills, customSkillError } from '../workspace/featureCatalog'
import CustomSkillDialog from '../components/workspace/CustomSkillDialog.vue'
import CompareRuns from '../components/workspace/CompareRuns.vue'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../components/ui/dialog'
import { Pin, PinOff } from 'lucide-vue-next'
import { pins, togglePin } from '../workspace/pins'
import { chatSyncError, chatSyncState, retryChatSync, syncStatusText } from '../workspace/chatSync.js'
import MarketMirrorLogo from '../components/MarketMirrorLogo.vue'
import ChatWorkspace from '../components/workspace/ChatWorkspace.vue'
import ConnectionsPage from '../components/workspace/ConnectionsPage.vue'
import WorkspaceOverview from '../components/workspace/WorkspaceOverview.vue'
import RunView from '../components/workspace/RunView.vue'
import { api, token, ensureSession } from '../workspace/api.js'
import { chooseTheme, storedTheme } from '../workspace/theme.js'
import { cloudAccount } from '../workspace/cloud.js'
import { account as accountRef, canEdit, role, signedIn, teamMode } from '../workspace/account.js'
import TeamPanel from '../components/workspace/TeamPanel.vue'
import OnboardingDialog from '../components/workspace/OnboardingDialog.vue'
import '../assets/workspace.css'
import '../assets/workspace-theme.css'
import '../assets/workspace-features.css'

const isMobile = ref(window.innerWidth <= 760)
function onResize() { isMobile.value = window.innerWidth <= 760 }
const projects = ref([])
const chats = ref([])
const customSkillOpen = ref(false), customSkillEditing = ref(null)
const canManageSkills = computed(() => !signedIn.value && (!cloudAccount.value || cloudAccount.value.workspace?.role === 'owner'))
function openCustomSkill(skill = null) { customSkillEditing.value = skill; customSkillOpen.value = true }
function reloadCustomSkills() { loadCustomSkills().catch(() => {}) }
const workingChats = ref(new Set())
function onChatStatus(event) { const {id,status} = event.detail || {}; if (typeof id !== 'string' || !id) return; const next = new Set(workingChats.value); if (status === 'working') next.add(id); else if (status === 'idle') next.delete(id); workingChats.value = next }
const activeChatMenu = ref(''), editingChat = ref(''), renameTitle = ref(''), renameId = ref(''), renameError = ref('')
const currentChat = computed(() => view.value === 'chat' ? chats.value.find(chat => chat.id === route.query.chat) : null)
function openRename(chat) { activeChatMenu.value = ''; renameId.value = chat.id; renameTitle.value = chat.customTitle || chat.title; renameError.value = ''; editingChat.value = chat.id; nextTick(() => { const input = document.querySelector('[data-inline-chat-name]'); input?.focus(); input?.select() }) }
function finishInlineRename() { if (!editingChat.value) return; if (!renameTitle.value.trim()) { editingChat.value = ''; return }; saveRename() }
function saveRename() {
 try {
  const title = renameTitle.value.trim(); if (!title) throw new Error('Give this chat a name.')
  const values = JSON.parse(localStorage.getItem('mm-conversations-v1') || '[]')
  const chat = values.find(item => item.id === renameId.value); if (!chat) throw new Error('This chat is no longer available in this browser.')
  chat.title = title; chat.customTitle = title
  localStorage.setItem('mm-conversations-v1', JSON.stringify(values)); window.dispatchEvent(new Event('mm-chats-updated')); editingChat.value = ''
 } catch (err) { renameError.value = err.message }
}
const inlineRenameError = ref('')
function renameInPlace(chat,event) {
 const title = event.target.value.trim(); inlineRenameError.value = ''
 if (!title) { event.target.value = chat.title; return }
 renameId.value = chat.id; renameTitle.value = title; saveRename()
 if (renameError.value) { inlineRenameError.value = renameError.value; event.target.value = chat.title }
}
function loadChats() { try { const data = JSON.parse(localStorage.getItem('mm-conversations-v1') || '[]'); chats.value = Array.isArray(data) ? data : [] } catch { chats.value = [] } }
const filteredChats = computed(() => chats.value.filter(c => String(c.title).toLowerCase().includes(search.value.trim().toLowerCase())))
const filteredProjects = computed(() => projects.value.filter(p => String(p.name).toLowerCase().includes(search.value.trim().toLowerCase())))
const searchResultCount = computed(() => filteredProjects.value.length + filteredChats.value.length + filteredRuns.value.length + searchedSkills.value.length)
const route = useRoute()
const router = useRouter()
const skillSearch = ref(''), skillCategory = ref('all')
const filteredSkills = computed(() => searchFeatures(skillSearch.value).filter(skill => skillCategory.value === 'all' || skill.group === skillCategory.value))
function openRun(name) { router.push({path:'/',query:{run:name,show:'reports'}}) }
const runs = ref([]), root = ref('mirofish_runs'), error = ref(''), projectsError = ref(''), search = ref(''), idea = ref(''), copied = ref('')
const provider = ref({ configured: false, models: [] }), menuOpen = ref(false), searchBox = ref(null)
const menuButton = ref(null)
function closeDrawer() { menuOpen.value = false }
function drawerItems() {
  return [...document.querySelectorAll('#ws-navigation a[href], #ws-navigation button:not([disabled])')]
}
function trapDrawerFocus(event) {
  if (!isMobile.value || !menuOpen.value || event.key !== 'Tab') return
  const items = drawerItems()
  if (!items.length) return
  const index = items.indexOf(document.activeElement)
  if (event.shiftKey && index <= 0) { event.preventDefault(); items[items.length - 1].focus() }
  else if (!event.shiftKey && index === items.length - 1) { event.preventDefault(); items[0].focus() }
}
watch(menuOpen, (open) => {
  if (!isMobile.value) return
  if (open) nextTick(() => drawerItems()[0]?.focus())
  else nextTick(() => menuButton.value?.focus())
})
const hasToken = ref(true), loaded = ref(false)
const systemTheme = window.matchMedia?.('(prefers-color-scheme: dark)')
const theme = ref(chooseTheme(storedTheme(), systemTheme?.matches))
function onSystemTheme(event) {
  if (storedTheme()) return
  theme.value = chooseTheme(null, event.matches)
}

const view = computed(() => (route.name === 'NotFound' ? 'notfound' : route.params.run ? 'run' : route.params.page || (route.path === '/' ? 'chat' : 'dashboard')))
const crumb = computed(() => (view.value === 'run' ? runs.value.find((r) => r.name === route.params.run)?.title || route.params.run
  : { dashboard: 'Overview', team: 'Workspace and team', chat: 'Chat', reports: 'Reports', projects: 'Projects', skills: 'Skills', connectors: 'Connections', compare: 'Compare', notfound: 'Page not found' }[view.value] || 'Chat'))
const pinnedRuns = computed(() => pins.value.map((name) => runs.value.find((r) => r.name === name)).filter(Boolean))
const shortcutsOpen = ref(false)
const syncStatus = computed(() => syncStatusText(chatSyncState.value, chatSyncError.value))
const spend = ref({ spent: 0, limit: 0 })
const money = (value) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value || 0)
const spendMeter = computed(() => {
  const spent = Number(spend.value.spent) || 0
  const limit = Number(spend.value.limit) || 0
  if (!spent && !limit) return ''
  return money(spent)
})
async function loadSpend() {
  try {
    const settings = await api('/api/workspace/settings')
    spend.value = {
      spent: Number(settings.spending?.process_spent_usd) || 0,
      limit: Number(settings.spending?.process_limit_usd) || 0,
    }
  } catch { /* the meter is optional */ }
}
const finishedToast = ref(null)
const notificationsAvailable = ref(typeof Notification !== 'undefined' && Notification.permission === 'default')
const canEnableNotifications = computed(() => notificationsAvailable.value && !runNotificationsOn())
function runNotificationsOn() { try { return localStorage.getItem('mm-run-notify') === '1' } catch { return false } }
function onRunFinished(event) {
  const detail = event.detail || {}
  finishedToast.value = detail
  if (document.hidden) document.title = `● ${document.title.replace(/^● /, '')}`
  if (runNotificationsOn() && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    new Notification(`${detail.title || 'A run'} finished`, { body: 'Open MarketMirror to see the result.' })
  }
}
async function enableRunNotifications() {
  if (typeof Notification === 'undefined') return
  const permission = await Notification.requestPermission()
  notificationsAvailable.value = permission === 'default'
  if (permission === 'granted') { try { localStorage.setItem('mm-run-notify', '1') } catch { /* this tab only */ } }
}
const isMac = /Mac|iPhone|iPad/.test(navigator.platform || '')
const shortcuts = [
  { keys: [isMac ? '⌘' : 'Ctrl', 'K'], what: 'Search projects, chats, runs and skills' },
  { keys: ['Enter'], what: 'Send a message (Shift Enter for a new line)' },
  { keys: ['/'], what: 'Find a skill from the chat box' },
  { keys: ['Alt', '1–4'], what: 'On a run page: switch between Results, Person, Report agent and Focus group' },
  { keys: ['↑', '↓'], what: 'Move through suggestions' },
  { keys: ['N'], what: 'Start a new chat' },
  { keys: ['G', 'then O / R / S'], what: 'Jump to Overview, Reports or Skills' },
  { keys: ['?'], what: 'Show these shortcuts' },
  { keys: ['Esc'], what: 'Close a menu or dialog' }
]
const contextualTitle = computed(() => view.value === 'chat' ? (currentChat.value?.title || projects.value.find(p => p.id === route.query.project)?.name || 'New conversation') : crumb.value)
// Keep the browser tab and history entry named after the page, chat or run, so
// several open tabs are distinguishable and a rename shows up at once.
watch(contextualTitle, (title) => {
  document.title = title ? `${title} · MarketMirror` : 'MarketMirror'
}, { immediate: true })
const greeting = computed(() => {
  const hr = new Date().getHours()
  return hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening'
})
const filteredRuns = computed(() => {
  const q = search.value.trim().toLowerCase()
  return q ? runs.value.filter((r) => `${r.title} ${r.name}`.toLowerCase().includes(q)) : runs.value
})
const runsNote = computed(() => (!hasToken.value ? 'Connect your local session to open saved runs.' : !loaded.value ? 'Loading runs…' : 'No saved runs yet. Run a market test, then it shows up here.'))
const providerLine = computed(() => (provider.value.configured ? provider.value.models?.[0]?.model || 'Model connected' : 'No model connected'))
const settingsLink = computed(() => `/setup#t=${encodeURIComponent(token())}`)

const skills = featureCatalog
const skillTints = ['rgba(142, 128, 220, .16)', 'rgba(77, 157, 147, .16)', 'rgba(229, 153, 108, .18)', 'rgba(104, 146, 220, .17)', 'rgba(191, 126, 169, .16)', 'rgba(155, 178, 102, .16)']
const runDestinations = [{ view: 'market', label: '3D world & audience' }, { view: 'results', label: 'Reports & decisions' }, { view: 'activity', label: 'Recorded agents' }, { view: 'thinking', label: 'Buyer responses' }, { view: 'feed', label: 'Social feed' }]
const matchingSkillGroups = computed(() => featureGroups.filter(group => filteredSkills.value.some(skill => skill.group === group)))
const searchedSkills = computed(() => search.value.trim() ? searchFeatures(search.value) : [])
const categoryIcons = { Workspace: FolderOpen, 'Show in chat': MessageSquare, 'Buyer research': UsersRound, Advertising: Megaphone, Strategy: Compass, 'Go to market': Sparkles, Validation: ChartNoAxesCombined }
const categoryDescriptions = { 'Show in chat': 'Every page and panel of the app, opened inline in the chat. Free: read from saved files, no model call.', Workspace: 'Your projects, saved evidence, and configuration.', 'Buyer research': 'Understand audiences through source evidence and simulated conversations.', Advertising: 'Explore creative performance and compare alternatives.', Strategy: 'Prepare campaigns and tests around a clear decision.', 'Go to market': 'Work through positioning, sales, pricing, and buyer journeys.', Validation: 'Check simulated conclusions against real outcomes.', 'Custom skills': 'Reusable instructions saved by this workspace.' }
const skillIcons = {
 project: FolderOpen, runs: Layers, settings: Settings2, models: Cpu, connectors: Plug, search: Search, health: ShieldCheck, report: FileText, simulation: Workflow,
 'seed-check': BookOpen, 'market-test': FlaskConical, research: Search, intake: Database, analytics: ChartNoAxesCombined, personas: UsersRound, ask: MessageSquare, 'focus-group': UsersRound, survey: ClipboardList, questionnaire: ClipboardList, 'choice-test': Scale, context: Brain, thoughts: Brain,
 'ads-import': Megaphone, actuals: Database, 'ad-patterns': Image, 'creative-check': Camera, 'feed-test': Layers, ideas: Lightbulb, captions: FileText, backtest: GitCompare,
 campaign: Target, test: FlaskConical, website: Globe, email: Mail, pitch: Mic, panel: UsersRound, objections: MessageSquare,
 committee: Network, creative: Image, battlecard: ShieldCheck, journey: Route, pricing: Tag, competitors: GitCompare, teardown: Globe, roleplay: Mic, whatif: Split, personalize: Target, geo: Globe, voc: MessageSquare, cascade: Network, 'gtm-suite': Compass,
 predict: ChartNoAxesCombined, forecast: Clock, study: Layers, calibrate: Scale, holdout: Split, split: Split, benchmark: Scale, compare: GitCompare, spend: Wallet,
}
function skillLink(skill) { return { path: '/', query: skill.custom ? { skill: skill.skillId } : skill.view ? { open: skill.id } : skill.action ? { action: skill.action } : { prompt: skill.prompt } } }
async function deleteChat(chat) {
  activeChatMenu.value = ''
  if (!confirm(`Delete “${chat.title}”? This cannot be undone.`)) return
  try {
    await api(`/api/workspace/chats/${encodeURIComponent(chat.id)}`, { method: 'DELETE' })
  } catch (e) {
    error.value = e.message
    return
  }
  chats.value = chats.value.filter(item => item.id !== chat.id)
  try { localStorage.setItem('mm-conversations-v1', JSON.stringify(chats.value)) } catch { /* the server copy is gone */ }
  window.dispatchEvent(new Event('mm-chats-updated'))
  if (route.query.chat === chat.id) router.push('/')
}
async function moveChat(chatId) {
  activeChatMenu.value = ''
  menuOpen.value = false
  const chat = chats.value.find(item => item.id === chatId)
  if (view.value !== 'chat') await router.push({ path: '/', query: { chat: chatId, ...(chat?.project ? { project: chat.project } : {}) } })
  await nextTick()
  window.dispatchEvent(new CustomEvent('mm-move-chat', { detail: { chatId } }))
}

watch(theme, (value) => { document.documentElement.dataset.theme = value }, { immediate: true })
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  if (signedIn.value) api('/api/workspace/preferences', { method: 'PUT', body: { user: { theme: theme.value } } }).catch(() => {})
  try {
    localStorage.setItem('mm-theme', theme.value)
  } catch {
    /* the theme still changes for this page */
  }
}

async function newChat() {
  menuOpen.value = false
  await router.push({ path: '/', query: { new: String(Date.now()) } })
}
async function openChatAction(event) {
  menuOpen.value = false
  if (view.value !== 'chat') await router.push('/')
  await nextTick()
  window.dispatchEvent(new CustomEvent(event))
}
function createProject() { openChatAction('mm-create-project') }
function openSettings() { openChatAction('mm-open-settings') }
const accountState = computed(() => accountRef.value)
const onboardingOpen = ref(false)
async function loadOnboarding() {
  if (cloudAccount.value || (teamMode.value && !signedIn.value)) return
  try {
    const state = await api('/api/workspace/onboarding')
    if (!state.steps?.dismissed) onboardingOpen.value = true
  } catch { /* an older backend has no onboarding; the app works without it */ }
}
async function loadUserTheme() {
  if (!signedIn.value) return
  try { const prefs = await api('/api/workspace/preferences'); if (prefs.user?.theme) { theme.value = prefs.user.theme; localStorage.setItem('mm-theme', theme.value) } } catch { /* keep this browser's choice */ }
}
function onAccountChanged() { loadChats(); refresh(); loadOnboarding(); loadUserTheme() }
async function loadProjects() {
  if (!token() && !signedIn.value) return
  try { const data = await api('/api/workspace/projects'); projects.value = Array.isArray(data) ? data : []; projectsError.value = '' } catch { projectsError.value = 'Projects could not load.' }
}
function openChatMenu(chat) {
  activeChatMenu.value = chat.id
  nextTick(() => document.querySelector(`[data-chat-menu="${chat.id}"]`)?.closest('.ws-chat-row')?.querySelector('[role="menuitem"]')?.focus())
}
function onChatMenuKeydown(event) {
  const items = [...event.currentTarget.querySelectorAll('[role="menuitem"]')]
  const index = items.indexOf(document.activeElement)
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const step = event.key === 'ArrowDown' ? 1 : -1
    items[(index + step + items.length) % items.length]?.focus()
  } else if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    items[event.key === 'Home' ? 0 : items.length - 1]?.focus()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    activeChatMenu.value = ''
    event.currentTarget.closest('.ws-chat-row')?.querySelector('[data-chat-menu]')?.focus()
  }
}
function searchResults() {
  return [...document.querySelectorAll('.ws-side-scroll a[href], .ws-side-scroll .ws-history button, .ws-side-scroll .ws-skill-card')]
}
function onSearchKeydown(event) {
  if (event.key !== 'ArrowDown') return
  const items = searchResults()
  if (!items.length) return
  event.preventDefault()
  items[0].focus()
}
function onResultsKeydown(event) {
  if (!search.value.trim() || !['ArrowDown', 'ArrowUp', 'Escape'].includes(event.key)) return
  if (event.key === 'Escape') {
    event.preventDefault()
    searchBox.value?.focus()
    return
  }
  const items = searchResults()
  const index = items.indexOf(document.activeElement)
  if (!items.length) return
  event.preventDefault()
  const step = event.key === 'ArrowDown' ? 1 : -1
  const next = index < 0 ? items[0] : items[Math.min(items.length - 1, Math.max(0, index + step))]
  next?.focus()
}
let gPressedAt = 0
function onSlash(e) {
  if (e.key === 'Escape') { menuOpen.value = false; gPressedAt = 0 }
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) || document.activeElement?.isContentEditable
  const dialogOpen = Boolean(document.querySelector('[role="dialog"]'))
  if (!typing && !dialogOpen && !e.metaKey && !e.ctrlKey && !e.altKey) {
    const key = e.key.toLowerCase()
    if (key === 'g') { gPressedAt = Date.now(); return }
    if (Date.now() - gPressedAt < 1500) {
      const target = { o: '/workspace', r: '/workspace/reports', s: '/workspace/skills' }[key]
      if (target) {
        e.preventDefault()
        gPressedAt = 0
        router.push(target)
        return
      }
    }
    if (key === 'n') {
      e.preventDefault()
      newChat()
      return
    }
  }
  if (!typing && e.key === '?') {
    e.preventDefault()
    shortcutsOpen.value = true
    return
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    menuOpen.value = true
    nextTick(() => searchBox.value?.focus())
  }
}

let refreshTimer
const refreshing = ref(false)
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await ensureSession()
    hasToken.value = true
    const [list, meta] = await Promise.all([api('/api/runs'), api('/api/workflows/meta').catch(() => null)])
    runs.value = Array.isArray(list.runs) ? list.runs : []
    root.value = String(list.root || 'mirofish_runs').split('/').slice(-1)[0]
    if (meta?.provider) provider.value = meta.provider
    error.value = ''
    loadProjects()
  } catch (e) {
    error.value = e.message
  } finally {
    loaded.value = true
    refreshing.value = false
  }
}
function refreshVisible() { if (!document.hidden) { document.title = document.title.replace(/^● /, ''); refresh() } }
onMounted(() => {
  systemTheme?.addEventListener?.('change', onSystemTheme)
  loadChats()
  window.addEventListener('mm-chats-updated', loadChats)
  window.addEventListener('mm-chats-loaded', loadChats)
  window.addEventListener('mm-chat-status', onChatStatus)
  window.addEventListener('mm-projects-updated', loadProjects)
  window.addEventListener('mm-provider-changed', refresh)
  window.addEventListener('mm-runs-updated', refresh)
  document.addEventListener('keydown', onSlash)
  window.addEventListener('resize', onResize)
  document.addEventListener('visibilitychange', refreshVisible)
  window.addEventListener('mm-account-changed', onAccountChanged)
  window.addEventListener('mm-workspace-renamed', onAccountChanged)
  window.addEventListener('mm-run-finished', onRunFinished)
  refresh()
  loadSpend()
  loadOnboarding()
  loadUserTheme()
  refreshTimer = setInterval(refreshVisible, 15000)
})
onUnmounted(() => {
  systemTheme?.removeEventListener?.('change', onSystemTheme)
  window.removeEventListener('mm-account-changed', onAccountChanged)
  window.removeEventListener('mm-workspace-renamed', onAccountChanged)
  window.removeEventListener('mm-runs-updated', refresh)
  window.removeEventListener('mm-run-finished', onRunFinished)
  window.removeEventListener('mm-chats-updated', loadChats)
  window.removeEventListener('mm-chats-loaded', loadChats)
  window.removeEventListener('mm-chat-status', onChatStatus)
  window.removeEventListener('mm-projects-updated', loadProjects)
  window.removeEventListener('mm-provider-changed', refresh)
  document.removeEventListener('keydown', onSlash)
  window.removeEventListener('resize', onResize)
  document.removeEventListener('visibilitychange', refreshVisible)
  clearInterval(refreshTimer)
})

const RunCard = defineComponent({
  props: { run: { type: Object, required: true } },
  setup(p) {
    const when = (x) => {
      try {
        return new Date(x).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
      } catch {
        return ''
      }
    }
    return () => h(RouterLink, { to: {path:'/',query:{run:p.run.name,show:'reports'}}, class: 'ws-card', style: { '--tint': 'rgba(31, 107, 79, 0.1)' } }, () => [
      h('span', { class: 'ws-ico' }, '▦'),
      p.run.decision ? h('span', { class: `ws-tag pill ${String(p.run.decision).toLowerCase().replace(' ', '-')}` }, String(p.run.decision).toUpperCase()) : null,
      h('b', p.run.title),
      h('span', [p.run.people ? `${p.run.people} simulated people · ` : '', when(p.run.updated_at || p.run.mtime * 1000)].join(''))
    ])
  }
})
</script>

<style>
.ws-skill-card-wrap{position:relative;min-width:0}.ws-skill-card-wrap>.ws-skill-card{height:100%}.ws-skill-edit{position:absolute;right:17px;top:21px;display:grid;place-items:center;width:28px;height:28px;border:0;border-radius:7px;background:transparent;color:var(--muted);cursor:pointer}.ws-skill-edit:hover{background:var(--panel-2);color:var(--text)}.ws-skill-source{position:absolute;right:52px;top:27px;font-size:10px;color:var(--muted)!important;text-decoration:underline!important}
.ws-skill-card-footer>span{min-width:0;max-width:calc(100% - 24px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ws-current-chat-dot{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--text);margin-left:auto;flex-shrink:0}.ws-chat-working{margin-left:auto;flex-shrink:0;animation:ws-chat-working 1s linear infinite}@keyframes ws-chat-working{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.ws-chat-working{animation:none}}
.ws-chat-action-menu{width:180px!important;padding:5px!important;border-radius:12px!important;border-color:var(--line)!important;background:var(--panel)!important;color:var(--text)!important}.ws-chat-action-menu button{display:flex;align-items:center;gap:9px;width:100%;padding:10px;border:0;border-radius:8px;background:none;color:inherit;text-align:left;font:inherit;font-size:12px;cursor:pointer}.ws-chat-action-menu button:hover{background:var(--panel-2)}.ws-chat-action-menu .ws-chat-delete{color:var(--no)}.ws-rename-title{display:flex;align-items:center;gap:8px;min-width:0;padding:0;border:0;background:none;color:var(--text);font:inherit;font-weight:550;cursor:pointer}.ws-rename-title>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ws-rename-title>svg{flex-shrink:0;color:var(--muted);opacity:.65}.ws-rename-dialog{width:min(440px,calc(100vw - 32px))!important;border-color:var(--line)!important;border-radius:21px!important;background:var(--panel)!important;color:var(--text)!important}.ws-rename-dialog [data-slot=dialog-description]{font-size:12px;line-height:1.7;color:var(--muted)}.ws-rename-dialog form{display:grid;gap:18px}.ws-rename-dialog label{display:grid;gap:8px;font-size:12px}.ws-rename-dialog input{padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:var(--panel-2);color:var(--text);font:inherit}.ws-rename-dialog form>div{display:flex;justify-content:flex-end;gap:9px}.ws-rename-dialog button[type=submit]{background:var(--accent);color:white}.ws-rename-dialog form>p{color:#bb6b62;font-size:12px}
.ws-skills-page{max-width:1320px;margin-inline:auto}.ws-skill-navigation{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 20px}.ws-skill-navigation button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:35px;padding:7px 11px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--muted);font:inherit;font-size:11px;cursor:pointer}.ws-skill-navigation button[aria-pressed=true]{color:var(--text);border-color:color-mix(in srgb,var(--accent) 50%,var(--line));background:var(--accent-2)}.ws-skill-navigation button>span{font-size:10px;opacity:.7}.ws-skill-group-heading{margin-top:28px;margin-bottom:16px}.ws-skill-group-heading>.ws-skill-group{margin:0 0 6px;font-size:16px}.ws-skill-group-heading>p{font-size:12px;line-height:1.7;color:var(--muted)}.ws-skills-page .ws-skill-card{display:flex;flex-direction:column;min-height:210px;padding:22px;border-radius:16px;gap:10px}.ws-skills-page .ws-skill-card>.ws-ico{width:39px;height:39px;border-radius:11px;margin-bottom:4px;background:var(--tint);color:var(--text)}.ws-skills-page .ws-skill-card>b{font-size:13px;line-height:1.5}.ws-skills-page .ws-skill-card>span:not(.ws-ico):not(.ws-skill-card-footer){font-size:12px;line-height:1.7;color:var(--muted)}.ws-skill-card-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:auto;padding-top:12px;color:var(--muted);font-size:10px}.ws-skill-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;min-height:220px;border:1px dashed var(--line);border-radius:16px;color:var(--muted);text-align:center;padding:25px}.ws-skill-empty h2{font-size:16px;color:var(--text);font-weight:550}.ws-skill-empty p{font-size:12px}.ws-skill-empty button{padding:8px 12px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;font-size:11px;cursor:pointer}@media(max-width:600px){.ws-skill-navigation{gap:6px}.ws-skill-navigation button{font-size:10px;padding:7px 9px}.ws-skills-page .ws-skill-card{min-height:190px;padding:19px}.ws-skill-group-heading>p{font-size:11px}}
.ws-chat-row{display:flex;align-items:center;gap:2px;min-width:0}.ws-chat-row>a{flex:1;min-width:0}.ws-chat-move{display:grid;place-items:center;flex-shrink:0;width:25px;height:28px;border:0;border-radius:6px;background:transparent;color:var(--muted);cursor:pointer}.ws-chat-move:hover,.ws-chat-move:focus-visible{background:var(--panel-2);color:var(--text)}.ws-run-shortcuts{margin:2px 0 8px 21px;padding-left:9px;border-left:1px solid var(--line)}.ws-run-shortcuts>a{min-height:29px!important;padding:5px 9px!important;font-size:10px!important}.ws-skill-group{font-size:15px;font-weight:550;letter-spacing:-.2px;margin:25px 0 14px}.ws-skill-card .ws-ico{display:grid;place-items:center}.ws-skill-card>.ws-note{font-size:10px!important}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>

<style scoped>.ws-inline-title{min-width:0;max-width:100%;position:relative}.ws-inline-title .ws-chat-title-input{width:clamp(120px,28vw,420px);max-width:100%;height:34px;border:1px solid transparent;border-radius:8px;padding:6px 9px;margin-left:-9px;background:transparent;color:var(--text);font:inherit;font-size:13px;font-weight:550;text-overflow:ellipsis}.ws-inline-title .ws-chat-title-input:hover{background:var(--panel);border-color:var(--line)}.ws-inline-title .ws-chat-title-input:focus{background:var(--panel);border-color:var(--accent);outline:2px solid color-mix(in srgb,var(--accent) 18%,transparent);text-overflow:clip}.ws-inline-title>span{position:absolute;top:100%;left:0;font-size:12px;color:var(--no);background:var(--panel);padding:8px;z-index:10}@media(max-width:500px){.ws-inline-title .ws-chat-title-input{width:150px}}</style>

<style scoped>.ws-chat-inline-form{flex:1;min-width:0;position:relative}.ws .ws-chat-inline-form input{width:100%;min-width:0;height:34px;border:1px solid var(--accent);border-radius:8px;background:var(--panel);padding:6px 9px;font-size:13px;outline:2px solid color-mix(in srgb,var(--accent) 15%,transparent)}.ws-chat-inline-form>span{font-size:11px;color:var(--no)}</style>
