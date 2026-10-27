<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { engine } from '../store'
import { ago, human } from '../fmt'
import Badge from '../components/Badge.vue'
import PageHead from '../components/PageHead.vue'

const router = useRouter()
const s = computed(() => engine.state)
const open = computed(() => s.value.tickets.filter(t => !['resolved', 'closed'].includes(t.status)))
const startOfDay = new Date().setHours(0, 0, 0, 0)
const m = computed<{ t: string; n: number; q?: Record<string, string>; to?: string }[]>(() => [
  { t: 'Open tickets', n: open.value.length, q: { status: 'open' } as Record<string, string> },
  { t: 'High-priority tickets', n: open.value.filter(t => ['high', 'critical'].includes(t.priority)).length, q: { priority: 'high' } as Record<string, string> },
  { t: 'Awaiting review', n: engine.pending().length, to: '/reviews' },
  { t: 'Investigations today', n: s.value.runs.filter(r => r.started >= startOfDay).length, to: '/runs' },
  { t: 'Failed runs', n: s.value.runs.filter(r => r.status === 'failed').length, to: '/runs?status=failed' }
])
const by = (key: 'status' | 'priority', order: string[]) => order.map(k => ({ k, n: s.value.tickets.filter(t => t[key] === k).length }))
const statusData = computed(() => by('status', ['open', 'in_progress', 'waiting_info', 'resolved', 'closed']))
const prioData = computed(() => by('priority', ['critical', 'high', 'medium', 'low']))
const max = (d: { n: number }[]) => Math.max(1, ...d.map(x => x.n))
const go = (q: Record<string, string>) => router.push({ path: '/tickets', query: q })
const click = (x: (typeof m.value)[number]) => (x.to ? router.push(x.to) : go(x.q!))
</script>
<template>
  <PageHead title="Operations Overview" sub="Synthetic operations data — portfolio demo. All values come from the local seed and recorded events.">
    <RouterLink to="/tour"><button class="primary">Run sample walkthrough</button></RouterLink>
  </PageHead>
  <div class="grid g5">
    <button v-for="x in m" :key="x.t" class="card metric" @click="click(x)"><div class="n">{{ x.n }}</div><div class="t">{{ x.t }}</div></button>
  </div>
  <div class="grid g2" style="margin-top:14px">
    <section class="card"><h2>Ticket volume by status <span class="muted small">(all synthetic tickets, current snapshot)</span></h2>
      <button v-for="d in statusData" :key="d.k" class="bar" @click="go({ status: d.k })"><span class="l">{{ human(d.k) }}</span><span class="track"><span class="fill" :style="{ width: (d.n / max(statusData)) * 100 + '%', display: 'block' }" /></span><span class="v">{{ d.n }}</span></button>
    </section>
    <section class="card"><h2>Priority distribution <span class="muted small">(current snapshot)</span></h2>
      <button v-for="d in prioData" :key="d.k" class="bar" @click="go({ priority: d.k })"><span class="l">{{ d.k }}</span><span class="track"><span class="fill" :style="{ width: (d.n / max(prioData)) * 100 + '%', display: 'block' }" /></span><span class="v">{{ d.n }}</span></button>
    </section>
    <section class="card"><div class="row between"><h2>Pending review</h2><RouterLink to="/reviews">View all</RouterLink></div>
      <p v-if="!engine.pending().length" class="muted">Nothing awaiting review. Open a ticket and start an investigation.</p>
      <div v-for="p in engine.pending().slice(0, 5)" :key="p.id" class="row between" style="margin:6px 0">
        <RouterLink :to="`/reviews/${p.id}`">{{ p.id }} · {{ p.summary }}</RouterLink><Badge :v="p.risk" :label="p.risk + ' risk'" />
      </div>
    </section>
    <section class="card"><h2>System health &amp; recent failures</h2>
      <div class="row"><Badge v="info" label="Model mode: fixture" /><Badge v="info" label="Connectors: mock only" /><Badge :v="s.config.fault === 'none' ? 'ok' : 'warn'" :label="s.config.fault === 'none' ? 'No simulated faults' : 'Fault: ' + s.config.fault" /></div>
      <p v-if="!s.runs.some(r => r.status === 'failed')" class="muted">No failed runs recorded.</p>
      <div v-for="r in s.runs.filter(x => x.status === 'failed').slice(0, 4)" :key="r.id" style="margin:6px 0"><RouterLink :to="`/runs/${r.id}`">{{ r.id }}</RouterLink> · {{ r.ticketId }} · <span class="muted">{{ r.error }} · {{ ago(r.started) }}</span></div>
    </section>
    <section class="card" style="grid-column:1/-1"><h2>Recent activity</h2>
      <p v-if="!s.audit.length" class="muted">No activity yet.</p>
      <div v-for="a in s.audit.slice(0, 8)" :key="a.id" class="row" style="margin:4px 0"><Badge :v="a.result" /> <strong>{{ human(a.action) }}</strong> <span class="mono">{{ a.target }}</span> <span class="muted">{{ engine.userName(a.actor) }} · {{ ago(a.ts) }}</span></div>
    </section>
  </div>
</template>
