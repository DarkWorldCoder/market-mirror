import './components/workspace/modal-controls.css'
import { createApp } from 'vue'
import App from './App.vue'
import './assets/design-system.css'
import router from './router'
import i18n from './i18n'
import { ensureSession } from './workspace/api'
import { initializeCloud } from './workspace/cloud'
import { loadCustomSkills } from './workspace/featureCatalog'

const app = createApp(App)

app.use(router)
app.use(i18n)

Promise.allSettled([ensureSession(), initializeCloud()]).then(() => loadCustomSkills().catch(() => {})).then(() => app.mount('#app'))
