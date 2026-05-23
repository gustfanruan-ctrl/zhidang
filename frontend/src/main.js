import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia } from 'pinia'
import App from './App.vue'
import ChatPage from './pages/ChatPage.vue'
import TranscriptsPage from './pages/TranscriptsPage.vue'
import ReviewPage from './pages/ReviewPage.vue'
import ConfigPage from './pages/ConfigPage.vue'
import LlmPage from './pages/LlmPage.vue'
import MaintenancePage from './pages/MaintenancePage.vue'
import PowerMapPage from './pages/PowerMapPage.vue'
import PowerMapV2Page from './pages/PowerMapV2Page.vue'
import ChatV2Panel from './pages/ChatV2Panel.vue'
import LoginPage from './pages/LoginPage.vue'
import InitPage from './pages/InitPage.vue'
import SsoCallbackPage from './pages/SsoCallbackPage.vue'
import { api } from './api'
import './styles.css'
import './assets/tailwind.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/init', component: InitPage, meta: { public: true } },
    { path: '/login', component: LoginPage, meta: { public: true } },
    { path: '/sso/callback', component: SsoCallbackPage, meta: { public: true } },
    { path: '/chat', component: ChatPage },
    { path: '/review', component: ReviewPage },
    { path: '/transcripts', component: TranscriptsPage },
    { path: '/config', component: ConfigPage, meta: { superadminOnly: true } },
    { path: '/llm', component: LlmPage, meta: { superadminOnly: true } },
    { path: '/maintenance', component: MaintenancePage, meta: { superadminOnly: true } },
    { path: '/power-map', component: PowerMapV2Page },
    { path: '/power-map-chat', component: ChatV2Panel },
    { path: '/power-map-old', component: PowerMapPage },
  ],
})

let cachedMe = null
let systemInitialized = null

export function getCachedMe() { return cachedMe }

router.beforeEach(async (to) => {
  const tokenFromUrl = new URLSearchParams(window.location.search).get('token')
  if (tokenFromUrl) {
    localStorage.setItem('zhidang_token', tokenFromUrl)
    const url = new URL(window.location.href)
    url.searchParams.delete('token')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }
  const companyIdFromUrl = new URLSearchParams(window.location.search).get('company_id')
  if (companyIdFromUrl) {
    localStorage.setItem('zhidang_company_id', companyIdFromUrl)
  }

  if (systemInitialized === null) {
    const status = await api.get('/api/v1/system/status').then((r) => r.data).catch(() => ({ initialized: true }))
    systemInitialized = status.initialized
  }
  if (!systemInitialized && to.path !== '/init') return '/init'
  if (systemInitialized && to.path === '/init') return '/login'

  const token = localStorage.getItem('zhidang_token')
  if (!token) return to.meta.public ? true : '/login'
  if (to.path === '/login') return '/chat'

  const me = await api.get('/api/v1/me').then((r) => r.data).catch(() => null)
  if (!me) { cachedMe = null; return '/login' }
  cachedMe = me
  if (to.meta.superadminOnly && me.source !== 'superadmin') return '/chat'
  return true
})

createApp(App).use(createPinia()).use(router).mount('#app')
