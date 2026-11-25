import { watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
const Home = () => import('../views/Home.vue')
const LegacyHome = () => import('../views/LegacyHome.vue')
const Process = () => import('../views/MainView.vue')
const SimulationView = () => import('../views/SimulationView.vue')
const SimulationRunView = () => import('../views/SimulationRunView.vue')
const ReportView = () => import('../views/ReportView.vue')
const InteractionView = () => import('../views/InteractionView.vue')
const Workspace = () => import('../views/Workspace.vue')
const AuthView = () => import('../views/AuthView.vue')
import { account, loadAccount, sessionEnded } from '../workspace/account.js'

// Known before the first page renders: local mode, or team mode with or without someone signed in.
export const accountReady = loadAccount()
const AUTH_PAGES = new Set(['Login', 'Signup', 'Join'])

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Workspace
  },
  { path: '/start', name: 'Start', component: Home },
  { path: '/app', redirect: '/' },
  { path: '/workflows/:workflowId', name: 'Workflow', component: Home },
  { path: '/legacy', name: 'LegacyHome', component: LegacyHome },
  { path: '/workspace', name: 'Workspace', component: Workspace },
  { path: '/workspace/runs/:run', name: 'WorkspaceRun', component: Workspace },
  { path: '/workspace/:page(dashboard|chat|reports|projects|skills|connectors|compare|team)', name: 'WorkspacePage', component: Workspace },
  { path: '/login', name: 'Login', component: AuthView, props: { mode: 'login' } },
  { path: '/signup', name: 'Signup', component: AuthView, props: { mode: 'signup' } },
  { path: '/join', name: 'Join', component: AuthView, props: { mode: 'join' } },
  { path: '/team', redirect: '/workspace/team' },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: Process,
    props: true
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true
  },
  // An old bookmark or a mistyped address should land in the workspace shell
  // with a way back, not on an empty page.
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: Workspace }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  await accountReady
  const state = account.value
  if (state.mode !== 'accounts') return AUTH_PAGES.has(to.name) ? { path: '/' } : true
  if (!state.account && !AUTH_PAGES.has(to.name)) return { name: 'Login', query: to.fullPath !== '/' ? { next: to.fullPath } : {} }
  if (state.account && (to.name === 'Login' || to.name === 'Signup')) return { path: '/' }
  return true
})

// A session can end without a navigation (14 days, password change, removal).
// The API drops the person, and this sends them to sign-in with a way back.
watch(account, (state) => {
  if (state.mode !== 'accounts' || state.account) return
  const current = router.currentRoute.value
  if (AUTH_PAGES.has(current.name)) return
  router.replace({ name: 'Login', query: { next: current.fullPath, ...(sessionEnded.value ? { expired: '1' } : {}) } })
})

export default router
