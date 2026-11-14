import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
const LegacyHome = () => import('../views/LegacyHome.vue')
const Process = () => import('../views/MainView.vue')
const SimulationView = () => import('../views/SimulationView.vue')
const SimulationRunView = () => import('../views/SimulationRunView.vue')
const ReportView = () => import('../views/ReportView.vue')
const InteractionView = () => import('../views/InteractionView.vue')

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  { path: '/app', redirect: '/' },
  { path: '/workflows/:workflowId', name: 'Workflow', component: Home },
  { path: '/legacy', name: 'LegacyHome', component: LegacyHome },
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
