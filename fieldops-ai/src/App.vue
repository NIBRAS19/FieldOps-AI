<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { engine } from './store'
import LoginView from './views/LoginView.vue'

const route = useRoute(), router = useRouter()
const nav = [
  { to: '/overview', label: 'Overview', icon: '▦' }, { to: '/tickets', label: 'Tickets', icon: '☰' },
  { to: '/reviews', label: 'Reviews', icon: '✔' }, { to: '/runs', label: 'Runs', icon: '↯' },
  { to: '/knowledge', label: 'Knowledge', icon: '❒' }, { to: '/evaluations', label: 'Evaluations', icon: '◎' },
  { to: '/audit', label: 'Audit Log', icon: '≣' }, { to: '/settings', label: 'Settings', icon: '⚙' }
]
const collapsed = ref(false), menu = ref(false), mobile = ref(false), q = ref('')
const theme = ref(localStorage.getItem('fo-theme') ?? 'light')
watchEffect(() => { document.documentElement.dataset.theme = theme.value; localStorage.setItem('fo-theme', theme.value) })
const pending = computed(() => engine.pending().length)
const active = (to: string) => (route.meta.nav ?? route.path).toString().startsWith(to)
const search = () => { router.push({ path: '/tickets', query: { q: q.value } }); q.value = '' }
</script>

<template>
  <LoginView v-if="!engine.state.userId" />
  <div v-else class="shell" :class="{ collapsed, mobile }">
    <aside class="side" :aria-label="'Primary'">
      <div class="brand"><span class="logo">F</span><strong v-if="!collapsed">FieldOps AI</strong></div>
      <nav>
        <RouterLink v-for="n in nav" :key="n.to" :to="n.to" :class="{ on: active(n.to) }" @click="mobile = false">
          <span class="ico" aria-hidden="true">{{ n.icon }}</span><span v-if="!collapsed" class="lbl">{{ n.label }}</span>
          <span v-if="n.to === '/reviews' && pending" class="count">{{ pending }}</span>
        </RouterLink>
      </nav>
      <button class="ghost collapse" @click="collapsed = !collapsed" :aria-label="collapsed ? 'Expand sidebar' : 'Collapse sidebar'">{{ collapsed ? '»' : '« Collapse' }}</button>
    </aside>
    <div class="main">
      <div class="demo-banner" role="note">DEMO WORKSPACE · SYNTHETIC DATA · MOCK ACTIONS</div>
      <header class="top">
        <button class="ghost burger" aria-label="Menu" @click="mobile = !mobile">☰</button>
        <button class="chip clickable" :class="[engine.mode, { offline: engine.mode === 'live' && !engine.backendOnline }]" :title="`Click to toggle mode. Currently: ${engine.mode === 'live' ? 'Live API (FastAPI)' : 'Local Mock'}`" @click="engine.toggleMode()">
          {{ engine.mode === 'live' ? (engine.backendOnline ? '● Live API (FastAPI)' : '▲ Live API (Offline)') : '○ Local Mock Engine' }}
        </button>
        <button v-if="engine.mode === 'live'" class="icon-btn" :disabled="engine.isSyncing" title="Sync state from FastAPI backend" aria-label="Sync from backend" @click="engine.syncFromBackend()">
          <span :style="{ display: 'inline-block', transform: engine.isSyncing ? 'rotate(180deg)' : 'none', transition: 'transform 0.5s' }">↻</span>
        </button>
        <form class="gsearch" @submit.prevent="search"><input v-model="q" placeholder="Search tickets (ID, title, asset…)" aria-label="Global ticket search" /></form>
        <RouterLink class="icon-btn" to="/reviews" :title="`${pending} proposals awaiting review`" aria-label="Notifications">🔔<span v-if="pending" class="dot">{{ pending }}</span></RouterLink>
        <RouterLink class="icon-btn" to="/tour" title="Guided demo" aria-label="Guided demo">?</RouterLink>
        <button class="icon-btn" :aria-label="`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`" @click="theme = theme === 'light' ? 'dark' : 'light'">{{ theme === 'light' ? '☾' : '☀' }}</button>
        <div class="usermenu">
          <button class="ghost" @click="menu = !menu" :aria-expanded="menu">{{ engine.user.name }} · <span class="badge gray">simulated {{ engine.user.role }}</span></button>
          <div v-if="menu" class="dropdown" @mouseleave="menu = false">
            <p class="muted small">Simulated role. Demo only, not a security mechanism. Switching is audited.</p>
            <button v-for="u in engine.state.users.filter(x => x.active)" :key="u.id" :class="{ on: u.id === engine.user.id }" @click="engine.switchRole(u.id); menu = false">{{ u.name }} — {{ u.role }}</button>
            <hr /><button @click="engine.logout(); menu = false">Leave workspace</button>
          </div>
        </div>
      </header>
      <main class="content" tabindex="-1"><RouterView v-slot="{ Component }"><component :is="Component" :key="route.fullPath.split('?')[0]" /></RouterView></main>
    </div>
    <div class="toasts" aria-live="polite">
      <div v-for="t in engine.toasts" :key="t.id" class="toast" :class="t.kind" role="status">{{ t.msg }}</div>
    </div>
  </div>
</template>
