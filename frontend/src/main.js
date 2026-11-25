import './components/workspace/modal-controls.css'
import { createApp, watch } from 'vue'
import App from './App.vue'
import './assets/design-system.css'
import router, { accountReady } from './router'
import i18n from './i18n'
import { ensureSession } from './workspace/api'
import { initializeCloud } from './workspace/cloud'
import { loadCustomSkills } from './workspace/featureCatalog'
import { startWorkspaceData, watchAccount } from './workspace/workspaceData'
import { setFormatLocale } from './workspace/format'
import { signedIn } from './workspace/account'

const app = createApp(App)

// One locale for every number, currency and date in the shell.
watch(i18n.global.locale, setFormatLocale, { immediate: true })

app.use(router)
app.use(i18n)

accountReady
  .then(() => Promise.allSettled([ensureSession(), initializeCloud()]))
  .then(() => { watchAccount(); startWorkspaceData(); return signedIn.value ? undefined : loadCustomSkills().catch(() => {}) })
  .then(() => app.mount('#app'))
