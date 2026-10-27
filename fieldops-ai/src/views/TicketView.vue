<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { engine } from '../store'
import { ago, dt, human, sla } from '../fmt'
import type { EvidenceItem } from '../types'
import Badge from '../components/Badge.vue'
import Evidence from '../components/Evidence.vue'

const route = useRoute()
const t = computed(() => engine.ticket(route.params.id as string))
const runs = computed(() => engine.runsFor(route.params.id as string))
const latest = computed(() => runs.value[0])
const props = ref<EvidenceItem | null>(null)
const note = ref('')
const busy = computed(() => latest.value && ['queued', 'running'].includes(latest.value.status))
const ro = computed(() => engine.role === 'readonly')
const ticketProposals = computed(() => engine.state.proposals.filter(p => p.ticketId === route.params.id))
const related = computed(() => t.value ? engine.state.cases.filter(c => c.category === t.value!.category) : [])
const timeline = computed(() => {
  if (!t.value) return []
  const n = t.value.notes.map(x => ({ ts: x.ts, who: x.by === 'u-system' ? 'AI-approved action' : engine.userName(x.by), kind: x.kind, text: x.text }))
  const a = engine.state.audit.filter(x => x.target === t.value!.id).map(x => ({ ts: x.ts, who: engine.userName(x.actor), kind: x.action, text: x.detail }))
  return [...n, ...a].sort((x, y) => y.ts - x.ts)
})
const start = () => engine.attempt(() => { void engine.investigate(t.value!.id).catch(e => engine.toast(e.message, 'error')) })
const addNote = () => engine.attempt(async () => { await engine.addNote(t.value!.id, note.value); note.value = '' })
const aiLabel = computed(() => latest.value ? human(latest.value.status) : 'not started')
</script>
<template>
  <div v-if="!t" class="err">Ticket not found. <RouterLink to="/tickets">Back to queue</RouterLink></div>
  <template v-else>
    <div class="pagehead">
      <div>
        <div class="muted small"><RouterLink to="/tickets">Tickets</RouterLink> / {{ t.id }} <span class="badge amber">synthetic</span></div>
        <h1>{{ t.title }}</h1>
        <div class="row" style="margin-top:6px"><Badge :v="t.priority" /><Badge :v="t.status" /><Badge :v="sla(t).band" :label="'SLA: ' + sla(t).label" /><span class="muted">Assignee: {{ engine.userName(t.assignee) }} · Team: {{ t.team }}</span></div>
      </div>
      <div class="actions">
        <button v-if="busy" @click="engine.attempt(async () => { await engine.cancelRun(latest!.id) })">Cancel run</button>
        <button v-else-if="latest?.status === 'failed'" :disabled="ro" @click="engine.attempt(async () => { await engine.retryRun(latest!.id) })">Retry failed run</button>
        <button class="primary" :disabled="ro || busy" :title="ro ? 'Read-only role' : ''" @click="start">{{ runs.length ? 'Re-run investigation' : 'Investigate with FieldOps AI' }}</button>
      </div>
    </div>
    <div class="split">
      <div class="stack">
        <section class="card"><h2>Description</h2><p style="white-space:pre-wrap">{{ t.description }}</p>
          <dl class="kv"><dt>Category</dt><dd>{{ t.category }}</dd><dt>Customer</dt><dd>{{ t.customer ?? '—' }} <span class="muted">(synthetic alias)</span></dd><dt>Asset</dt><dd>{{ t.asset ?? '—' }}</dd><dt>Created</dt><dd>{{ dt(t.created) }}</dd><dt>SLA target</dt><dd>{{ dt(t.slaDue) }}</dd></dl>
        </section>
        <section class="card"><h2>Timeline &amp; notes</h2>
          <div class="row"><input v-model="note" placeholder="Add human note" style="flex:1" :disabled="ro" @keydown.enter="addNote" aria-label="Add human note" /><button :disabled="ro || !note" @click="addNote">Add note</button></div>
          <p v-if="!timeline.length" class="muted">No activity yet.</p>
          <div v-for="(e, i) in timeline" :key="i" class="note"><small>{{ human(e.kind) }} · {{ e.who }} · {{ ago(e.ts) }}</small>{{ e.text }}</div>
        </section>
        <section class="card"><h2>Related synthetic cases</h2>
          <p v-if="!related.length" class="muted">No related cases.</p>
          <div v-for="c in related" :key="c.id" class="note"><small>{{ c.id }}</small><strong>{{ c.title }}</strong><br />{{ c.resolution }}</div>
        </section>
      </div>
      <div class="stack">
        <section class="card">
          <div class="row between"><h2>FieldOps AI investigation</h2><Badge :v="latest?.status ?? 'not_started'" :label="aiLabel" /></div>
          <p class="muted small">Suggestions are advisory, not policy. Nothing changes until a person approves it in Reviews. Fixture model mode.</p>
          <p v-if="!latest" class="muted">Not started. Choose “Investigate with FieldOps AI”.</p>
          <ol v-if="latest && busy" class="timeline"><li v-for="(e, i) in latest.events" :key="i" :class="e.status"><strong>{{ human(e.step) }}</strong><div class="muted small">{{ e.detail }}</div></li><li><em class="muted">working…</em></li></ol>
          <div v-if="latest?.status === 'failed'" class="caveat"><strong>Run failed:</strong> {{ latest.error }}. No plan was produced and nothing was fabricated. Retry is safe.</div>
          <div v-if="latest?.output">
            <div v-if="latest.status === 'blocked'" class="caveat"><strong>Blocked by policy.</strong> No action was proposed. Escalate to a human lead.</div>
            <h3>Summary</h3><p>{{ latest.output.summary }}</p>
            <div class="row"><Badge v="info" :label="'Category: ' + latest.output.classification.category" /><Badge v="info" :label="'Urgency: ' + latest.output.classification.urgency" /><span class="muted small">Confidence {{ Math.round(latest.output.classification.confidence * 100) }}% (uncalibrated)</span></div>
            <h3 style="margin-top:12px">Recommended steps</h3>
            <p v-if="!latest.output.steps.length" class="muted">No evidence-backed steps. See caveats.</p>
            <div v-for="s in latest.output.steps" :key="s.n" class="step"><span class="n">{{ s.n }}</span><div>{{ s.instruction }}
              <button v-for="id in s.evidence_ids" :key="id" class="cite" @click="props = latest!.output!.evidence.find(e => e.chunk_id === id)!">{{ id }}</button></div></div>
            <h3 style="margin-top:12px">Draft response <span class="muted small">(not sent)</span></h3><pre>{{ latest.output.draft }}</pre>
            <h3>Caveats &amp; limitations</h3><div v-for="(l, i) in latest.output.limitations" :key="i" class="caveat">{{ l }}</div>
            <div class="row" style="margin-top:8px"><RouterLink :to="`/runs/${latest.id}`">Open run trace →</RouterLink></div>
          </div>
        </section>
        <section class="card"><h2>Proposed actions</h2>
          <p v-if="!ticketProposals.length" class="muted">None yet. Investigations create typed proposals that wait for review.</p>
          <div v-for="p in ticketProposals" :key="p.id" class="row between note"><RouterLink :to="`/reviews/${p.id}`">{{ p.summary }}</RouterLink><span class="row"><Badge :v="p.risk" :label="p.risk + ' risk'" /><Badge :v="p.status" /></span></div>
        </section>
        <section class="card"><h2>All investigations ({{ runs.length }})</h2>
          <p v-if="!runs.length" class="muted">No runs for this ticket.</p>
          <div v-for="r in runs" :key="r.id" class="row between" style="margin:4px 0"><RouterLink :to="`/runs/${r.id}`">{{ r.id }}</RouterLink><span class="muted small">{{ ago(r.started) }} · {{ engine.userName(r.by) }}</span><Badge :v="r.status" /></div>
        </section>
      </div>
    </div>
    <Evidence v-if="props" :item="props" @close="props = null" />
  </template>
</template>
