<script setup lang="ts">
import { ref } from 'vue'
import { engine } from '../store'
import { dt, human } from '../fmt'
import { ALLOWED_TOOLS, FORBIDDEN_TOOLS } from '../mock/policy'
import type { Fault, Role } from '../types'
import Badge from '../components/Badge.vue'
import Overlay from '../components/Overlay.vue'
import PageHead from '../components/PageHead.vue'
const admin = () => engine.role === 'admin'
const reset = ref(false), confirm = ref('')
const adapters = [{ id: 'ticketing', n: 'Ticketing system', d: 'Local synthetic ticket store' }, { id: 'knowledge', n: 'Knowledge source', d: 'Seeded Markdown/JSON corpus' }, { id: 'assets', n: 'Asset inventory', d: 'Synthetic asset aliases' }, { id: 'outbound', n: 'Outbound-response preview', d: 'Preview only; nothing is sent' }]
const num = (k: 'topK' | 'maxRetries' | 'approvalExpiryMin', e: Event) => engine.attempt(async () => { await engine.setConfig({ [k]: Math.max(0, +(e.target as HTMLInputElement).value) }) })
const doReset = () => engine.attempt(async () => { await engine.resetDemo(); reset.value = false; confirm.value = ''; engine.toast('Synthetic dataset reset', 'ok') })
</script>
<template>
  <PageHead title="Settings & Integrations" sub="Demo configuration. Changes are audited. No secrets are ever shown here.">
    <span v-if="!admin()" class="badge amber">Read-only: admin role required to change</span></PageHead>
  <div class="grid g2">
    <section class="card"><h2>Workspace &amp; model</h2><dl class="kv"><dt>Mode</dt><dd><Badge v="info" label="Demo workspace (simulated auth)" /></dd><dt>Backend connection</dt><dd><button class="chip clickable" :class="[engine.mode, { offline: engine.mode === 'live' && !engine.backendOnline }]" @click="engine.toggleMode()">{{ engine.mode === 'live' ? (engine.backendOnline ? '● Live FastAPI Backend (/api/v1)' : '▲ Live Mode (Backend Offline)') : '○ Local Mock Engine (Offline)' }}</button></dd><dt>Model mode</dt><dd><Badge v="info" label="Fixture (deterministic)" /></dd><dt>Live provider</dt><dd>Not configured. If one is added later, ticket text may be sent to that provider; the provider/model ID would be shown here. Credentials are never shown.</dd><dt>Connector mode</dt><dd>Mock only (MVP)</dd><dt>Dataset version</dt><dd>v{{ engine.state.datasetVersion }}</dd></dl></section>
    <section class="card"><h2>Policy &amp; budgets</h2>
      <label>Approval expiry (minutes)</label><input type="number" min="1" :value="engine.state.config.approvalExpiryMin" :disabled="!admin()" @change="num('approvalExpiryMin', $event)" />
      <label>Max retries (provider/repair)</label><input type="number" min="0" max="5" :value="engine.state.config.maxRetries" :disabled="!admin()" @change="num('maxRetries', $event)" />
      <label>Retrieval top-k</label><input type="number" min="1" max="8" :value="engine.state.config.topK" :disabled="!admin()" @change="num('topK', $event)" />
      <label>Simulated fault for next runs (demo of failure handling)</label>
      <select :value="engine.state.config.fault" :disabled="!admin()" @change="engine.attempt(async () => { await engine.setConfig({ fault: ($event.target as HTMLSelectElement).value as Fault }) })"><option value="none">none</option><option value="timeout">provider timeout</option><option value="malformed">malformed model output</option><option value="retrieval">retrieval failure</option></select>
      <p class="muted small">Retention: synthetic data resets with “Reset demo data”. Browser-local storage only.</p></section>
    <section class="card"><h2>Mock connectors</h2>
      <div v-for="a in adapters" :key="a.id" class="row between" style="margin:8px 0"><div><strong>{{ a.n }}</strong> <span class="badge amber">simulated</span><div class="muted small">{{ a.d }} · {{ engine.state.health[a.id] ? 'health checked ' + dt(engine.state.health[a.id]) : 'not health-checked yet' }}</div></div>
        <span class="row"><Badge :v="engine.state.health[a.id] ? 'ok' : 'info'" :label="engine.state.health[a.id] ? 'healthy (mock)' : 'mock mode'" /><button :disabled="!admin()" @click="engine.attempt(async () => { await engine.healthCheck(a.id) })">Check</button></span></div></section>
    <section class="card"><h2>Role management <span class="muted small">(simulated)</span></h2>
      <div v-for="u in engine.state.users" :key="u.id" class="row between" style="margin:6px 0"><span>{{ u.name }}</span>
        <select :value="u.role" :disabled="!admin() || u.id === engine.user.id" :aria-label="`Role for ${u.name}`" @change="engine.attempt(async () => { await engine.setRole(u.id, ($event.target as HTMLSelectElement).value as Role) })"><option v-for="r in ['admin', 'lead', 'agent', 'readonly']" :key="r">{{ r }}</option></select></div>
      <p class="muted small">You cannot change your own role. The approval policy cannot be bypassed by any role.</p></section>
    <section class="card" style="grid-column:1/-1"><h2>Allowlisted tools</h2>
      <div class="tablewrap"><table><thead><tr><th>Tool</th><th>Mode</th><th>Purpose</th><th>Approval</th><th>Side effects</th></tr></thead><tbody>
        <tr v-for="t in ALLOWED_TOOLS" :key="t.name"><td class="mono">{{ t.name }}</td><td>{{ t.mode }}</td><td>{{ t.purpose }}</td><td>{{ t.approval ? 'Required' : 'No' }}</td><td>{{ t.mode === 'Read' ? 'None' : 'Local mock only' }}</td></tr></tbody></table></div>
      <p class="muted small"><strong>Forbidden:</strong> {{ FORBIDDEN_TOOLS.join(', ') }}.</p></section>
    <section class="card" style="grid-column:1/-1"><h2>Dataset</h2><p class="muted">Reset regenerates the synthetic dataset, clears runs, proposals and evaluations, and records a reset event.</p>
      <button class="danger" :disabled="!admin()" @click="reset = true">Reset demo data…</button></section>
  </div>
  <Overlay v-if="reset" title="Reset demo data?" @close="reset = false">
    <p>This replaces all synthetic tickets, runs, proposals and evaluation results with a new dataset version. Type <strong>RESET</strong> to confirm.</p><input v-model="confirm" aria-label="Type RESET" />
    <template #footer><button @click="reset = false">Cancel</button><button class="danger" :disabled="confirm !== 'RESET'" @click="doReset">Reset dataset</button></template></Overlay>
</template>
