<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { engine } from '../store'
import { ago, dt, download, human } from '../fmt'
import Badge from '../components/Badge.vue'
import PageHead from '../components/PageHead.vue'
const route = useRoute(), router = useRouter()
const f = reactive({ status: (route.query.status as string) ?? '', ticket: '', by: '', error: '' })
const rows = computed(() => engine.state.runs.filter(r => (!f.status || r.status === f.status) && (!f.ticket || r.ticketId.toLowerCase().includes(f.ticket.toLowerCase())) && (!f.by || r.by === f.by) && (!f.error || r.error === f.error)))
const sel = ref<string[]>([])
const toggle = (id: string) => { sel.value = sel.value.includes(id) ? sel.value.filter(x => x !== id) : [...sel.value, id].slice(-2) }
const dur = (r: { started: number; ended?: number }) => (r.ended ? ((r.ended - r.started) / 1000).toFixed(1) + 's' : '—')
const exportMeta = () => download('runs-sanitized.json', rows.value.map(r => ({ id: r.id, ticket: r.ticketId, status: r.status, workflow: r.workflowVersion, prompt: r.promptVersion, started: r.started, ended: r.ended, error: r.error, steps: r.events.length, evaluation_label: r.label ?? null })))
const errors = computed(() => [...new Set(engine.state.runs.map(r => r.error).filter(Boolean))] as string[])
</script>
<template>
  <PageHead title="Run History" sub="Search prior investigations. Select two runs to compare.">
    <button :disabled="sel.length !== 2" @click="router.push({ path: `/runs/${sel[0]}`, query: { compare: sel[1] } })">Compare selected</button>
    <button @click="exportMeta">Export sanitized metadata</button>
  </PageHead>
  <div class="filters">
    <select v-model="f.status" aria-label="Status"><option value="">Any status</option><option v-for="s in ['ready_for_review', 'blocked', 'failed', 'cancelled', 'running']" :key="s" :value="s">{{ human(s) }}</option></select>
    <input v-model="f.ticket" placeholder="Ticket ID" aria-label="Ticket" />
    <select v-model="f.by" aria-label="Initiator"><option value="">Any initiator</option><option v-for="u in engine.state.users" :key="u.id" :value="u.id">{{ u.name }}</option></select>
    <select v-model="f.error" aria-label="Error category"><option value="">Any error</option><option v-for="e in errors" :key="e">{{ e }}</option></select>
  </div>
  <div class="tablewrap"><table>
    <thead><tr><th></th><th>Run</th><th>Ticket</th><th>Workflow</th><th>Result</th><th>Started by</th><th>Started</th><th>Duration</th><th>Review</th><th>Label</th><th></th></tr></thead>
    <tbody>
      <tr v-for="r in rows" :key="r.id">
        <td><input type="checkbox" :checked="sel.includes(r.id)" :aria-label="`Select ${r.id}`" @change="toggle(r.id)" /></td>
        <td><RouterLink :to="`/runs/${r.id}`" class="mono">{{ r.id }}</RouterLink></td><td><RouterLink :to="`/tickets/${r.ticketId}`">{{ r.ticketId }}</RouterLink></td><td class="mono">{{ r.workflowVersion }}</td>
        <td><Badge :v="r.status" /> <span class="muted small">{{ r.error }}</span></td><td>{{ engine.userName(r.by) }}</td><td :title="dt(r.started)">{{ ago(r.started) }}</td><td>{{ dur(r) }}</td>
        <td>{{ r.output?.proposalIds.length ? r.output.proposalIds.length + ' proposal(s)' : '—' }}</td><td>{{ r.label ? human(r.label) : '—' }}{{ r.evalSample ? ' · eval sample' : '' }}</td>
        <td><button v-if="r.status === 'failed'" :disabled="engine.role === 'readonly'" @click="engine.attempt(() => { void engine.retryRun(r.id) })">Retry</button></td>
      </tr>
      <tr v-if="!rows.length"><td colspan="11" class="empty">No runs yet. Open a ticket and start an investigation.</td></tr>
    </tbody></table></div>
</template>
