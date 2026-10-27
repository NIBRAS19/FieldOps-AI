<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { engine } from '../store'
import { ago, human } from '../fmt'
import { ACTIONS } from '../mock/policy'
import Badge from '../components/Badge.vue'
import PageHead from '../components/PageHead.vue'
const router = useRouter()
const f = reactive({ status: 'pending', risk: '', requester: '' })
const rows = computed(() => engine.state.proposals.filter(p =>
  (!f.status || (f.status === 'failed' ? p.status === 'simulated_failure' : f.status === 'approved' ? ['approved', 'simulated_success'].includes(p.status) : p.status === f.status)) &&
  (!f.risk || p.risk === f.risk) && (!f.requester || p.requester === f.requester)))
</script>
<template>
  <PageHead title="Review Inbox" sub="Proposed actions waiting for a human decision. Nothing executes automatically." />
  <div class="filters">
    <select v-model="f.status" aria-label="Status"><option value="">All</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="expired">Expired</option><option value="failed">Execution failed</option></select>
    <select v-model="f.risk" aria-label="Risk"><option value="">Any risk</option><option>high</option><option>medium</option><option>low</option></select>
    <select v-model="f.requester" aria-label="Requester"><option value="">Any requester</option><option v-for="u in engine.state.users" :key="u.id" :value="u.id">{{ u.name }}</option></select>
  </div>
  <div class="tablewrap"><table>
    <thead><tr><th>Proposal</th><th>Ticket</th><th>Action</th><th>Summary</th><th>Requester</th><th>Risk</th><th>Created</th><th>Expires</th><th>Status</th></tr></thead>
    <tbody>
      <tr v-for="p in rows" :key="p.id" class="click" :class="{ hi: p.status === 'pending' && p.risk === 'high' }" tabindex="0" @click="router.push(`/reviews/${p.id}`)" @keydown.enter="router.push(`/reviews/${p.id}`)">
        <td class="mono">{{ p.id }}</td><td class="mono">{{ p.ticketId }}</td><td>{{ ACTIONS[p.type].label }}</td><td>{{ p.summary }}</td><td>{{ engine.userName(p.requester) }}</td>
        <td><Badge :v="p.risk" :label="p.risk + (p.status === 'pending' && p.risk === 'high' ? ' · needs attention' : '')" /></td><td class="muted">{{ ago(p.created) }}</td><td class="muted">{{ p.status === 'pending' ? ago(p.expires) : '—' }}</td><td><Badge :v="p.status" /></td>
      </tr>
      <tr v-if="!rows.length"><td colspan="9" class="empty">No proposals in this view. Start an investigation from a ticket, or change the filter.</td></tr>
    </tbody></table></div>
</template>
