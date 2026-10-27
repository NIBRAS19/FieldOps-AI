<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { engine } from '../store'
import { dt, human } from '../fmt'
import { ACTIONS, STATUSES, canDecide } from '../mock/policy'
import { TEAMS } from '../mock/seed'
import type { EvidenceItem, Payload } from '../types'
import Badge from '../components/Badge.vue'
import Evidence from '../components/Evidence.vue'
import Overlay from '../components/Overlay.vue'

const route = useRoute()
const p = computed(() => engine.proposal(route.params.id as string))
const ticket = computed(() => p.value && engine.ticket(p.value.ticketId))
const run = computed(() => p.value && engine.run(p.value.runId))
const evidence = computed(() => (run.value?.output?.evidence ?? []).filter(e => p.value!.evidenceIds.includes(e.chunk_id)))
const modal = ref<'' | 'approve' | 'edit' | 'reject'>('')
const raw = ref(false)
const drawer = ref<EvidenceItem | null>(null)
const draft = reactive<Payload>({})
const reason = ref('unsupported'), comment = ref('')
const perm = computed(() => p.value ? canDecide(engine.role, engine.user.id, p.value) : { ok: false })
const live = computed(() => p.value?.status === 'pending' && Date.now() < p.value.expires)
const can = computed(() => perm.value.ok && live.value)
const rows = (pl: Payload) => Object.entries(pl).map(([k, v]) => [human(k), k === 'assignee' ? engine.userName(v as string) : String(v)])
const openEdit = () => { Object.assign(draft, p.value!.payload); modal.value = 'edit' }
const fields = computed(() => ACTIONS[p.value!.type].editable)
const submit = async (kind: 'approve' | 'edit_approve' | 'reject') => {
  try {
    await engine.decide(p.value!.id, kind, { hash: p.value!.hash, payload: kind === 'edit_approve' ? { ...draft } : undefined, reason: reason.value, comment: comment.value })
    modal.value = ''
    engine.toast(kind === 'reject' ? 'Proposal rejected. Nothing executed.' : `Approved. ${p.value!.status === 'simulated_success' ? 'Simulated action completed.' : 'Simulated execution recorded.'}`, kind === 'reject' ? 'info' : p.value!.status === 'simulated_success' ? 'ok' : 'info')
  } catch (err) {
    engine.toast((err as Error).message || 'Decision failed', 'error')
  }
}
</script>
<template>
  <div v-if="!p || !ticket" class="err">Proposal not found. <RouterLink to="/reviews">Back to inbox</RouterLink></div>
  <template v-else>
    <div class="pagehead"><div><div class="muted small"><RouterLink to="/reviews">Reviews</RouterLink> / {{ p.id }}</div><h1>{{ ACTIONS[p.type].label }}: {{ p.summary }}</h1>
      <div class="row" style="margin-top:6px"><Badge :v="p.status" /><Badge :v="p.risk" :label="p.risk + ' risk'" /><span class="muted">v{{ p.version }} · hash <span class="mono">{{ p.hash }}</span></span></div></div>
      <div class="actions"><button class="primary" :disabled="!can" @click="modal = 'approve'">Approve</button><button :disabled="!can" @click="openEdit">Edit &amp; Approve</button><button class="danger" :disabled="!can" @click="modal = 'reject'">Reject</button></div></div>
    <div v-if="!perm.ok" class="caveat">{{ (perm as any).why ?? 'Not permitted' }}</div>
    <div v-else-if="p.status !== 'pending'" class="caveat">This proposal is {{ human(p.status) }} and can no longer be decided. A decision cannot be overwritten.</div>
    <div v-else-if="!live" class="caveat">This proposal expired and cannot be approved. Re-run the investigation to create a fresh one.</div>
    <div class="split">
      <div class="stack">
        <section class="card"><div class="sim-banner">SIMULATED LOCAL ACTION — target connector: mock ticketing (no external system is touched)</div>
          <h2>Exact payload</h2><p class="muted">{{ ACTIONS[p.type].desc }}</p>
          <dl class="kv"><template v-for="[k, v] in rows(p.payload)" :key="k"><dt>{{ k }}</dt><dd style="white-space:pre-wrap">{{ v }}</dd></template></dl>
          <button class="ghost" @click="raw = !raw">{{ raw ? 'Hide' : 'Show' }} raw JSON</button><pre v-if="raw">{{ JSON.stringify({ type: p.type, ticket: p.ticketId, version: p.version, hash: p.hash, payload: p.payload }, null, 2) }}</pre></section>
        <section class="card"><h2>Rationale &amp; expected effect</h2><p>{{ p.rationale }}</p>
          <dl class="kv"><dt>Expected effect</dt><dd>{{ p.expectedEffect }}</dd><dt>Reversal note</dt><dd>{{ p.rollback }}</dd><dt>Risk reason</dt><dd>{{ p.riskReason }}</dd><dt>Limitations</dt><dd>{{ run?.output?.limitations.join(' ') ?? '—' }}</dd></dl></section>
        <section class="card"><h2>Evidence</h2><p v-if="!evidence.length" class="muted">No cited evidence for this proposal.</p>
          <div v-for="e in evidence" :key="e.chunk_id" class="note"><small>{{ e.title }} v{{ e.version }} · {{ e.claim }}</small>{{ e.snippet }}<div><button class="cite" @click="drawer = e">Open source ({{ e.chunk_id }})</button></div></div></section>
      </div>
      <div class="stack">
        <section class="card"><h2>Context</h2><dl class="kv"><dt>Ticket</dt><dd><RouterLink :to="`/tickets/${ticket.id}`">{{ ticket.id }}</RouterLink> — {{ ticket.title }}</dd><dt>Ticket status</dt><dd><Badge :v="ticket.status" /></dd><dt>Requested by</dt><dd>{{ engine.userName(p.requester) }}</dd><dt>Run</dt><dd><RouterLink :to="`/runs/${p.runId}`">{{ p.runId }}</RouterLink></dd><dt>Created</dt><dd>{{ dt(p.created) }}</dd><dt>Approval expires</dt><dd>{{ dt(p.expires) }}</dd>
          <dt>Idempotency</dt><dd>{{ engine.state.executed.includes(`${p.id}:${p.hash}`) ? 'Already executed — retry will not duplicate.' : 'Not executed yet.' }}</dd></dl></section>
        <section v-if="p.decision || p.result" class="card"><h2>Decision &amp; result</h2><dl class="kv"><dt>Decision</dt><dd>{{ p.decision ? human(p.decision.action) + ' by ' + engine.userName(p.decision.by) + ' · ' + dt(p.decision.at) : '—' }}</dd><dt v-if="p.decision?.reason">Reason</dt><dd v-if="p.decision?.reason">{{ p.decision.reason }} {{ p.decision.comment }}</dd><dt>Simulated result</dt><dd>{{ p.result ?? '—' }}</dd></dl></section>
        <section class="card"><h2>Version history</h2><p v-if="!p.history.length" class="muted">Original proposal, no edits.</p>
          <div v-for="h in p.history" :key="h.version" class="note"><small>v{{ h.version }} · {{ h.note }} · {{ engine.userName(h.by) }}</small><pre>{{ JSON.stringify(h.payload, null, 2) }}</pre></div></section>
      </div>
    </div>
    <Overlay v-if="modal === 'approve'" title="Confirm approval" @close="modal = ''">
      <p>You are approving <strong>{{ ACTIONS[p.type].label }}</strong> on <strong>{{ p.ticketId }}</strong>. This applies only to version {{ p.version }} (<span class="mono">{{ p.hash }}</span>) and will change only the local synthetic record.</p>
      <dl class="kv"><template v-for="[k, v] in rows(p.payload)" :key="k"><dt>{{ k }}</dt><dd style="white-space:pre-wrap">{{ v }}</dd></template></dl>
      <template #footer><button @click="modal = ''">Cancel</button><button class="primary" @click="submit('approve')">Approve exactly this</button></template></Overlay>
    <Overlay v-if="modal === 'edit'" title="Edit & approve" @close="modal = ''">
      <p class="muted">Only schema-approved fields can change. The edit is revalidated and creates a new version and hash; the original is kept.</p>
      <template v-for="f in fields" :key="f"><label>{{ human(f) }}</label>
        <textarea v-if="f === 'text'" v-model="draft.text" />
        <select v-else-if="f === 'assignee'" v-model="draft.assignee"><option v-for="u in engine.state.users.filter(x => x.role !== 'readonly')" :key="u.id" :value="u.id">{{ u.name }}</option></select>
        <select v-else-if="f === 'team'" v-model="draft.team"><option v-for="t in TEAMS" :key="t">{{ t }}</option></select>
        <select v-else v-model="draft.to"><option v-for="s in STATUSES" :key="s" :value="s">{{ human(s) }}</option></select></template>
      <h3 style="margin-top:12px">Before / after</h3>
      <div class="diff"><div class="b"><strong>Before</strong>{{ '\n' + rows(p.payload).map(r => r.join(': ')).join('\n') }}</div><div class="a"><strong>After</strong>{{ '\n' + rows({ ...p.payload, ...draft }).map(r => r.join(': ')).join('\n') }}</div></div>
      <template #footer><button @click="modal = ''">Cancel</button><button class="primary" @click="submit('edit_approve')">Validate, save &amp; approve</button></template></Overlay>
    <Overlay v-if="modal === 'reject'" title="Reject proposal" @close="modal = ''">
      <p>Rejected proposals never execute and cannot be revived by replaying a request.</p>
      <label>Reason</label><select v-model="reason"><option v-for="r in ['unsupported', 'unsafe', 'incorrect', 'unnecessary', 'other']" :key="r">{{ r }}</option></select>
      <label>Comment (optional)</label><textarea v-model="comment" />
      <template #footer><button @click="modal = ''">Cancel</button><button class="danger" @click="submit('reject')">Reject</button></template></Overlay>
    <Evidence v-if="drawer" :item="drawer" @close="drawer = null" />
  </template>
</template>
