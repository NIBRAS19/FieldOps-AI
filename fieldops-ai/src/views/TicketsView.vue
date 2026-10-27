<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { engine } from '../store'
import { ago, human, sla } from '../fmt'
import { STATUSES } from '../mock/policy'
import type { Category, Priority } from '../types'
import Badge from '../components/Badge.vue'
import Overlay from '../components/Overlay.vue'
import PageHead from '../components/PageHead.vue'

const route = useRoute(), router = useRouter()
const KEYS = ['q', 'status', 'priority', 'category', 'assignee', 'ai', 'sla', 'sort', 'page'] as const
const f = reactive<Record<string, string>>({})
const read = () => KEYS.forEach(k => { f[k] = (route.query[k] as string) ?? '' })
read()
watch(f, () => router.replace({ query: Object.fromEntries(KEYS.filter(k => f[k]).map(k => [k, f[k]])) }), { deep: true })
watch(() => route.query, read)

const PR: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
const rows = computed(() => {
  const q = f.q.toLowerCase()
  let r = engine.state.tickets.filter(t =>
    (!q || [t.id, t.title, t.description, t.asset, t.customer].some(x => x?.toLowerCase().includes(q))) &&
    (!f.status || t.status === f.status) && (!f.priority || t.priority === f.priority) && (!f.category || t.category === f.category) &&
    (!f.assignee || (f.assignee === 'none' ? !t.assignee : t.assignee === f.assignee)) &&
    (!f.ai || engine.aiState(t.id) === f.ai) && (!f.sla || sla(t).band === f.sla))
  const s = f.sort || 'priority'
  r = [...r].sort((a, b) => s === 'priority' ? PR[a.priority] - PR[b.priority] : s === 'updated' ? b.updated - a.updated : s === 'created' ? b.created - a.created : a.slaDue - b.slaDue)
  return r
})
const size = 8
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / size)))
const page = computed(() => Math.min(pages.value, Math.max(1, +f.page || 1)))
const view = computed(() => rows.value.slice((page.value - 1) * size, page.value * size))
const clear = () => KEYS.forEach(k => (f[k] = ''))
const open = (id: string) => router.push(`/tickets/${id}`)

const show = ref(false)
const form = reactive({ title: '', description: '', category: 'other' as Category, priority: 'medium' as Priority, asset: '', customer: '' })
const create = () => engine.attempt(async () => {
  const t = await engine.createTicket({ ...form, asset: form.asset || undefined, customer: form.customer || undefined })
  show.value = false; Object.assign(form, { title: '', description: '', asset: '', customer: '' }); engine.toast(`Created synthetic ticket ${t.id}`, 'ok'); open(t.id)
})
const ro = computed(() => engine.role === 'readonly')
</script>
<template>
  <PageHead title="Ticket Queue" sub="Triage and find the next ticket. Filters are kept in the URL.">
    <button class="primary" :disabled="ro" @click="show = true">+ Create synthetic ticket</button>
  </PageHead>
  <div class="filters">
    <input v-model="f.q" placeholder="Search ID, title, asset, customer" aria-label="Search tickets" />
    <select v-model="f.status" aria-label="Status"><option value="">Any status</option><option v-for="s in STATUSES" :key="s" :value="s">{{ human(s) }}</option></select>
    <select v-model="f.priority" aria-label="Priority"><option value="">Any priority</option><option v-for="p in ['critical', 'high', 'medium', 'low']" :key="p">{{ p }}</option></select>
    <select v-model="f.category" aria-label="Category"><option value="">Any category</option><option v-for="c in ['access', 'connectivity', 'device', 'application', 'request', 'other']" :key="c">{{ c }}</option></select>
    <select v-model="f.assignee" aria-label="Assignee"><option value="">Any assignee</option><option value="none">Unassigned</option><option v-for="u in engine.state.users" :key="u.id" :value="u.id">{{ u.name }}</option></select>
    <select v-model="f.ai" aria-label="AI run state"><option value="">Any AI state</option><option v-for="s in ['not_started', 'running', 'ready_for_review', 'blocked', 'failed', 'cancelled']" :key="s" :value="s">{{ human(s) }}</option></select>
    <select v-model="f.sla" aria-label="SLA band"><option value="">Any SLA</option><option value="breached">Breached</option><option value="at_risk">At risk</option><option value="ok">OK</option></select>
    <select v-model="f.sort" aria-label="Sort"><option value="">Sort: priority</option><option value="updated">Last updated</option><option value="created">Created</option><option value="sla">SLA proximity</option></select>
    <button @click="clear">Reset</button>
  </div>
  <div class="tablewrap">
    <table>
      <thead><tr><th>ID</th><th>Title</th><th>Category</th><th>Priority</th><th>Status</th><th>Assignee</th><th>SLA target</th><th>Updated</th><th>AI state</th></tr></thead>
      <tbody>
        <tr v-for="t in view" :key="t.id" class="click" tabindex="0" @click="open(t.id)" @keydown.enter="open(t.id)">
          <td class="mono">{{ t.id }}</td><td><strong>{{ t.title }}</strong><div class="muted small">{{ t.asset }} {{ t.customer }}</div></td><td>{{ t.category }}</td>
          <td><Badge :v="t.priority" /></td><td><Badge :v="t.status" /></td>
          <td @click.stop><select :value="t.assignee ?? ''" :disabled="ro" :aria-label="`Assign ${t.id}`" @change="engine.attempt(async () => { await engine.assignDirect(t.id, ($event.target as HTMLSelectElement).value || null) })"><option value="">Unassigned</option><option v-for="u in engine.state.users.filter(x => x.role !== 'readonly')" :key="u.id" :value="u.id">{{ u.name }}</option></select></td>
          <td><Badge :v="sla(t).band" :label="sla(t).label" /></td><td class="muted">{{ ago(t.updated) }}</td>
          <td @click.stop><Badge :v="engine.aiState(t.id)" /><button v-if="engine.aiState(t.id) === 'not_started' && !ro" class="ghost" @click="open(t.id)">Open to investigate</button></td>
        </tr>
        <tr v-if="!view.length"><td colspan="9" class="empty">No tickets match these filters. <button @click="clear">Clear filters</button></td></tr>
      </tbody>
    </table>
  </div>
  <div class="pager"><span class="muted">{{ rows.length }} tickets · page {{ page }} / {{ pages }}</span>
    <button :disabled="page <= 1" @click="f.page = String(page - 1)">Prev</button><button :disabled="page >= pages" @click="f.page = String(page + 1)">Next</button></div>

  <Overlay v-if="show" title="Create synthetic ticket" @close="show = false">
    <span class="badge amber">synthetic ticket</span>
    <label>Title *</label><input v-model="form.title" style="width:100%" />
    <label>Description *</label><textarea v-model="form.description" />
    <div class="row"><div><label>Category</label><select v-model="form.category"><option v-for="c in ['access', 'connectivity', 'device', 'application', 'request', 'other']" :key="c">{{ c }}</option></select></div>
      <div><label>Priority</label><select v-model="form.priority"><option v-for="p in ['low', 'medium', 'high', 'critical']" :key="p">{{ p }}</option></select></div></div>
    <div class="row"><div><label>Asset (optional)</label><input v-model="form.asset" /></div><div><label>Customer alias (optional)</label><input v-model="form.customer" /></div></div>
    <template #footer><button @click="show = false">Cancel</button><button class="primary" @click="create">Create</button></template>
  </Overlay>
</template>
