<script setup lang="ts">
import { computed } from 'vue'
import { engine } from '../store'
import PageHead from '../components/PageHead.vue'
const runs = computed(() => engine.state.runs.filter(r => r.ticketId === 'FO-1001'))
const prop = computed(() => engine.state.proposals.filter(p => p.ticketId === 'FO-1001'))
const steps = computed(() => [
  { t: 'Open the seeded VPN connectivity ticket', to: '/tickets/FO-1001', done: true, hint: 'FO-1001: VPN fails after password change.' },
  { t: 'Start an investigation and inspect evidence', to: '/tickets/FO-1001', done: runs.value.some(r => r.output), hint: 'Open a citation. Notice the unreviewed community tip was quarantined, not cited.' },
  { t: 'Review a proposed action', to: prop.value[0] ? `/reviews/${prop.value[0].id}` : '/reviews', done: prop.value.length > 0, hint: 'Nothing has changed yet. Inspect the exact payload and the SIMULATED banner.' },
  { t: 'Approve the simulated action', to: '/reviews', done: prop.value.some(p => p.status === 'simulated_success'), hint: 'Approve the internal note. Only the local record changes.' },
  { t: 'See the audit event and run trace', to: runs.value[0] ? `/runs/${runs.value[0].id}` : '/audit', done: engine.state.audit.some(a => a.action === 'simulated_execution'), hint: 'Trace comes from persisted events. Check Audit Log for the simulated execution.' },
  { t: 'Run the evaluation suite and inspect a blocked case', to: '/evaluations', done: engine.state.evalRuns.length > 0, hint: 'Look at E14 (refund + deletion request): blocked with no proposal.' }
])
</script>
<template>
  <PageHead title="Guided Demo" sub="3–5 minute route. Completion ticks come from persisted state, not animations." />
  <div class="card"><div v-for="(s, i) in steps" :key="i" class="row between" style="padding:10px 0;border-bottom:1px solid var(--line)">
    <div class="row"><span class="badge" :class="s.done ? 'green' : 'gray'">{{ s.done ? '✓' : i + 1 }}</span><div><strong>{{ s.t }}</strong><div class="muted small">{{ s.hint }}</div></div></div>
    <RouterLink :to="s.to"><button :class="{ primary: !s.done }">Go</button></RouterLink></div>
    <p class="muted small" style="margin-top:12px">Tip: use Settings → simulated fault to demonstrate timeout, malformed output, and retrieval failure handling. Admins can reset the dataset in Settings.</p></div>
</template>
