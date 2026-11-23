import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
const LegacyHome = () => import('../views/LegacyHome.vue')
const Process = () => import('../views/MainView.vue')
const SimulationView = () => import('../views/SimulationView.vue')
const SimulationRunView = () => import('../views/SimulationRunView.vue')
const ReportView = () => import('../views/ReportView.vue')
const InteractionView = () => import('../views/InteractionView.vue')
const Workspace = () => import('../views/Workspace.vue')

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  { path: '/app', redirect: '/' },
  { path: '/workflows/:workflowId', name: 'Workflow', component: Home },
  { path: '/legacy', name: 'LegacyHome', component: LegacyHome },
  { path: '/workspace', name: 'Workspace', component: Workspace },
  { path: '/workspace/runs/:run', name: 'WorkspaceRun', component: Workspace },
  { path: '/workspace/sims/:sim', name: 'WorkspaceSim', component: Workspace },
  { path: '/workspace/:page(projects|skills|connectors|agents|inbox)', name: 'WorkspacePage', component: Workspace },
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
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
