import './components/workspace/modal-controls.css'
import { createApp } from 'vue'
import App from './App.vue'
import './assets/design-system.css'
import router, { accountReady } from './router'
import i18n from './i18n'
import { ensureSession } from './workspace/api'
import { initializeCloud } from './workspace/cloud'
import { loadCustomSkills } from './workspace/featureCatalog'
import { startWorkspaceData, watchAccount } from './workspace/workspaceData'

const app = createApp(App)

app.use(router)
app.use(i18n)

accountReady
  .then(() => Promise.allSettled([ensureSession(), initializeCloud()]))
  .then(() => { watchAccount(); startWorkspaceData(); return loadCustomSkills().catch(() => {}) })
  .then(() => app.mount('#app'))
