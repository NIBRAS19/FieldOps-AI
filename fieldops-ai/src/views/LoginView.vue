<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { engine } from '../store'
const pick = ref(engine.state.users[0]?.id || 'u-lead')
watchEffect(() => {
  if (engine.state.users.length && !engine.state.users.some(u => u.id === pick.value)) {
    const lead = engine.state.users.find(u => u.role === 'lead') || engine.state.users[0]
    pick.value = lead.id
  }
})
const desc: Record<string, string> = { admin: 'Manage settings, sources, roles, reset data', lead: 'Run investigations, review and decide on proposals', agent: 'Investigate, edit drafts; cannot self-approve high-risk', readonly: 'Explore tickets, runs and evaluations only' }
</script>
<template>
  <div class="login">
    <section class="card login-card">
      <div class="brand"><span class="logo">F</span><strong>FieldOps AI</strong></div>
      <h1>Human-reviewed operations agent</h1>
      <p class="muted">An AI-assisted ticket-resolution workspace. The agent proposes; people approve. Approved actions only change a local synthetic record.</p>
      <div class="warn-box" role="alert"><strong>Demo access mode.</strong> This is not real authentication and no identity is verified. All data is synthetic and all integrations are simulated.</div>
      <fieldset>
        <legend>Choose a simulated role</legend>
        <label v-for="u in engine.state.users" :key="u.id" class="radio" :class="{ on: pick === u.id }">
          <input type="radio" name="role" :value="u.id" v-model="pick" />
          <span><strong>{{ u.name }}</strong> <span class="badge gray">{{ u.role }}</span><br /><small class="muted">{{ desc[u.role] }}</small></span>
        </label>
      </fieldset>
      <div class="row between" style="margin: 12px 0 6px">
        <span class="muted small">Backend connection:</span>
        <button type="button" class="chip clickable" :class="[engine.mode, { offline: engine.mode === 'live' && !engine.backendOnline }]" :title="`Click to toggle mode. Currently: ${engine.mode === 'live' ? 'Live API (FastAPI)' : 'Local Mock'}`" @click="engine.toggleMode()">
          {{ engine.mode === 'live' ? (engine.backendOnline ? '● Live API (FastAPI)' : '▲ Live API (Offline)') : '○ Local Mock Engine' }}
        </button>
      </div>
      <button class="primary wide" @click="engine.login(pick)">Enter demo workspace</button>
      <p class="muted small">Proposed portfolio MVP · not a deployed product · no measured business impact is claimed.</p>
    </section>
  </div>
</template>
