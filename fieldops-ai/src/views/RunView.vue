<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { engine } from '../store'
import { dt, human } from '../fmt'
import type { RunEvent } from '../types'
import Badge from '../components/Badge.vue'
import Overlay from '../components/Overlay.vue'

const route = useRoute()
const r = computed(() => engine.run(route.params.id as string))
const other = computed(() => (route.query.compare ? engine.run(route.query.compare as string) : undefined))
const step = ref<RunEvent | null>(null)
const label = ref<'helpful' | 'partially_helpful' | 'unhelpful'>('helpful'), reason = ref('')
const props = computed(() => r.value ? engine.state.proposals.filter(p => p.runId === r.value!.id) : [])
const cmp = (x: typeof r.value) => x && ({
  Status: human(x.status), 'Workflow / prompt': `${x.workflowVersion} / ${x.promptVersion}`, 'Top-k / retries': `${x.config.topK} / ${x.config.maxRetries}`, 'Simulated fault': x.config.fault,
  Steps: x.events.length, Citations: x.output?.evidence.length ?? 0, 'Recommended steps': x.output?.steps.length ?? 0, Proposals: x.output?.proposalIds.length ?? 0, Limitations: x.output?.limitations.length ?? 0
})
const copy = () => { void navigator.clipboard?.writeText(r.value!.id); engine.toast('Run ID copied', 'ok') }
</script>
<template>
  <div v-if="!r" class="err">Run not found. <RouterLink to="/runs">Back to runs</RouterLink></div>
  <template v-else>
    <div class="pagehead"><div><div class="muted small"><RouterLink to="/runs">Runs</RouterLink> / {{ r.id }}</div><h1>Investigation run <span class="mono">{{ r.id }}</span></h1>
      <div class="row" style="margin-top:6px"><Badge :v="r.status" /><span class="muted">Ticket <RouterLink :to="`/tickets/${r.ticketId}`">{{ r.ticketId }}</RouterLink> · {{ r.workflowVersion }} · {{ r.promptVersion }} · fixture model · {{ dt(r.started) }} → {{ dt(r.ended) }}</span></div></div>
      <div class="actions"><button @click="copy">Copy run ID</button><button :disabled="engine.role === 'readonly'" @click="engine.attempt(() => { void engine.investigate(r!.ticketId) })">Rerun (current config)</button><button :disabled="engine.role !== 'admin'" @click="engine.attempt(() => engine.markEvalSample(r!.id))">Mark as evaluation sample</button></div></div>
    <div class="split">
      <section class="card"><h2>Run timeline <span class="muted small">(persisted events)</span></h2>
        <p v-if="!r.events.length" class="muted">No events recorded.</p>
        <ol class="timeline"><li v-for="(e, i) in r.events" :key="i" :class="['click', e.status]" tabindex="0" @click="step = e" @keydown.enter="step = e">
          <div class="row between"><strong>{{ human(e.step) }}</strong><span class="row"><Badge :v="e.status" /><span class="muted small">{{ e.durationMs }} ms</span></span></div><div class="muted small">{{ e.detail.slice(0, 120) }}{{ e.detail.length > 120 ? '…' : '' }}</div></li></ol>
        <div v-if="r.error" class="caveat">Error category: {{ r.error }}</div>
      </section>
      <div class="stack">
        <section class="card"><h2>Run summary</h2><dl class="kv"><dt>Final disposition</dt><dd><Badge :v="r.status" /></dd><dt>Config</dt><dd class="mono">top-k {{ r.config.topK }}, max retries {{ r.config.maxRetries }}, fault {{ r.config.fault }}</dd><dt>Citations</dt><dd>{{ r.output?.evidence.length ?? 0 }}</dd><dt>Proposals</dt>
          <dd><span v-for="p in props" :key="p.id" class="row"><RouterLink :to="`/reviews/${p.id}`">{{ p.id }}</RouterLink> <Badge :v="p.status" /></span><span v-if="!props.length">none</span></dd><dt>Human edits</dt><dd>{{ props.filter(p => p.history.length).length }} edited proposal(s)</dd></dl>
          <h3 style="margin-top:12px">Structured output</h3><pre v-if="r.output">{{ JSON.stringify({ ...r.output, evidence: r.output.evidence.map(e => ({ source_id: e.source_id, chunk_id: e.chunk_id, claim: e.claim })), draft: undefined }, null, 2) }}</pre><p v-else class="muted">No output (run {{ r.status }}).</p></section>
        <section class="card"><h2>Reviewer label</h2><p class="muted small">Labels never rewrite the original run output.</p>
          <p v-if="r.label">Current: <strong>{{ human(r.label) }}</strong> — {{ r.labelReason }}</p>
          <div class="row"><select v-model="label"><option value="helpful">helpful</option><option value="partially_helpful">partially helpful</option><option value="unhelpful">unhelpful</option></select><input v-model="reason" placeholder="Short reason" style="flex:1" /><button :disabled="!['admin', 'lead'].includes(engine.role)" @click="engine.attempt(async () => { await engine.labelRun(r!.id, label, reason) })">Save label</button></div></section>
      </div>
    </div>
    <section v-if="other" class="card" style="margin-top:14px"><h2>Compare {{ r.id }} vs {{ other.id }}</h2>
      <div class="tablewrap"><table><thead><tr><th>Field</th><th>{{ r.id }}</th><th>{{ other.id }}</th></tr></thead>
        <tbody><tr v-for="(v, k) in cmp(r)" :key="k"><td>{{ k }}</td><td>{{ v }}</td><td :style="{ fontWeight: String((cmp(other) as any)[k]) !== String(v) ? 700 : 400 }">{{ (cmp(other) as any)[k] }}</td></tr></tbody></table></div>
      <p class="muted small">Differences are bolded. Two runs are not enough to declare either one “better”.</p></section>
    <Overlay v-if="step" :title="human(step.step)" side @close="step = null">
      <dl class="kv"><dt>Status</dt><dd><Badge :v="step.status" /></dd><dt>Time</dt><dd>{{ dt(step.ts) }}</dd><dt>Duration</dt><dd>{{ step.durationMs }} ms (measured locally)</dd><dt>Attempt / retries</dt><dd>{{ step.attempt ?? '—' }}</dd><dt>Source IDs</dt><dd class="mono">{{ step.sourceIds?.join(', ') ?? '—' }}</dd><dt>Tokens / cost</dt><dd>n/a (fixture mode, no provider)</dd></dl>
      <h3 style="margin-top:12px">Sanitized detail</h3><p>{{ step.detail }}</p><p class="muted small">Secrets and raw prompt content are never stored in run events.</p>
    </Overlay>
  </template>
</template>
