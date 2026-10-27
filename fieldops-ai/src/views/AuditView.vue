<script setup lang="ts">
import { computed, reactive } from 'vue'
import { engine } from '../store'
import { dt, download, human } from '../fmt'
import Badge from '../components/Badge.vue'
import PageHead from '../components/PageHead.vue'
const f = reactive({ actor: '', action: '', target: '', result: '', from: '', to: '' })
const visible = computed(() => engine.role === 'readonly' ? engine.state.audit.filter(a => !['demo_login', 'simulated_role_switch', 'config_changed', 'role_changed'].includes(a.action)) : engine.state.audit)
const rows = computed(() => visible.value.filter(a =>
  (!f.actor || a.actor === f.actor) && (!f.action || a.action === f.action) && (!f.target || a.target.toLowerCase().includes(f.target.toLowerCase())) && (!f.result || a.result === f.result) &&
  (!f.from || a.ts >= new Date(f.from).getTime()) && (!f.to || a.ts <= new Date(f.to).getTime() + 86_400_000)))
const actions = computed(() => [...new Set(engine.state.audit.map(a => a.action))].sort())
const canExport = computed(() => ['admin', 'lead'].includes(engine.role))
const exp = () => { download('audit-sanitized.json', rows.value.map(a => ({ ...a }))); engine.audit('audit_exported', 'audit', 'info', `${rows.value.length} events exported (sanitized).`) }
</script>
<template>
  <PageHead title="Audit Log" sub="Append-only record of who did what. Corrections are new events, never edits.">
    <button :disabled="!canExport" :title="canExport ? '' : 'Admins and leads only'" @click="exp">Export sanitized JSON</button></PageHead>
  <p v-if="engine.role === 'readonly'" class="muted small">Showing the demo-visible subset for the read-only role.</p>
  <div class="filters">
    <select v-model="f.actor" aria-label="Actor"><option value="">Any actor</option><option v-for="u in engine.state.users" :key="u.id" :value="u.id">{{ u.name }}</option><option value="system">System</option></select>
    <select v-model="f.action" aria-label="Event"><option value="">Any event</option><option v-for="a in actions" :key="a" :value="a">{{ human(a) }}</option></select>
    <input v-model="f.target" placeholder="Target ID" aria-label="Target" />
    <select v-model="f.result" aria-label="Result"><option value="">Any result</option><option v-for="r in ['success', 'denied', 'failure', 'info']" :key="r">{{ r }}</option></select>
    <input v-model="f.from" type="date" aria-label="From date" /><input v-model="f.to" type="date" aria-label="To date" />
  </div>
  <div class="tablewrap"><table>
    <thead><tr><th>Time</th><th>Actor / role</th><th>Event</th><th>Target</th><th>Result</th><th>Detail</th><th>Run</th><th>Mode</th></tr></thead>
    <tbody><tr v-for="a in rows" :key="a.id"><td class="muted">{{ dt(a.ts) }}</td><td>{{ engine.userName(a.actor) }} <span class="muted small">({{ a.role }})</span></td><td>{{ human(a.action) }}</td><td class="mono">{{ a.target }}</td><td><Badge :v="a.result" /></td><td>{{ a.detail }}</td>
      <td><RouterLink v-if="a.runId" :to="`/runs/${a.runId}`" class="mono">{{ a.runId }}</RouterLink></td><td><span class="badge amber">simulated</span></td></tr>
      <tr v-if="!rows.length"><td colspan="8" class="empty">No audit events match.</td></tr></tbody></table></div>
</template>
