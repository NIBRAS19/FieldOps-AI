<script setup lang="ts">
import { computed, ref } from 'vue'
import { engine } from '../store'
import { dt, download, human } from '../fmt'
import { DATASET, runEval, summarize } from '../mock/evals'
import Badge from '../components/Badge.vue'
import PageHead from '../components/PageHead.vue'
const busy = ref(false)
const runs = computed(() => engine.state.evalRuns)
const idx = ref(0), cmpIdx = ref(-1)
const cur = computed(() => runs.value[idx.value]), prev = computed(() => runs.value[cmpIdx.value])
const sum = computed(() => cur.value && summarize(cur.value))
const psum = computed(() => prev.value && summarize(prev.value))
const cat = ref('')
const rows = computed(() => (cur.value?.results ?? []).filter(r => !cat.value || r.category === cat.value))
const cats = computed(() => [...new Set((cur.value?.results ?? []).map(r => r.category))])
const go = async () => {
  busy.value = true
  try { const r = await runEval({ ...engine.state.config }, engine.user.id); engine.state.evalRuns.unshift(r); idx.value = 0; engine.audit('evaluation_run', r.id, 'success', `${r.results.length} cases on ${r.dataset}.`); engine.toast('Evaluation finished', 'ok') }
  finally { busy.value = false }
}
const pct = (n: number) => Math.round(n * 100) + '%'
const cards = computed(() => sum.value ? [
  { t: 'Dataset', v: `${DATASET} · ${sum.value.n} cases`, d: 'Versioned synthetic cases covering each PRD category. The PRD asks for 50+ before claiming broad coverage.' },
  { t: 'Cases passed', v: `${sum.value.pass} / ${sum.value.n}`, d: 'A case passes only when every expectation check passes. Not a single quality score.' },
  { t: 'Citation coverage', v: `${pct(sum.value.citationCoverage)} (n=${sum.value.covN})`, d: 'Share of recommended steps whose citations exist in the authorized retrieved set, over cases that produced steps.' },
  { t: 'Action-policy pass', v: pct(sum.value.policyPass), d: 'Cases where only allowlisted actions were proposed and blocked requests produced none.' },
  { t: 'Schema-valid output', v: `${pct(sum.value.schemaValid)} (n=${sum.value.svN})`, d: 'Outputs that validate against the contract, over cases that produced an output.' },
  { t: 'Latency p50 / p95', v: `${sum.value.p50} / ${sum.value.p95} ms`, d: 'Local fixture execution time per case, not provider latency.' },
  { t: 'Provider errors', v: String(sum.value.providerErrors), d: 'Cases where a simulated provider/retrieval fault occurred (expected for fault-injection cases).' }
] : [])
</script>
<template>
  <PageHead title="Evaluations" sub="Repeatable behavior checks on a versioned synthetic dataset. Fixture model mode.">
    <button class="primary" :disabled="busy || !['admin', 'lead'].includes(engine.role)" @click="go">{{ busy ? 'Running…' : 'Run evaluation suite' }}</button>
    <button :disabled="!cur" @click="download(cur!.id + '.json', cur)">Export JSON</button></PageHead>
  <div v-if="!cur" class="card empty">No evaluation runs yet. Admins and leads can run the suite; it uses the current Settings configuration.</div>
  <template v-else>
    <div class="row" style="margin-bottom:10px"><label style="margin:0">Run</label>
      <select v-model="idx"><option v-for="(r, i) in runs" :key="r.id" :value="i">{{ r.id }} · {{ dt(r.ts) }}</option></select>
      <label style="margin:0">Compare with</label><select v-model="cmpIdx"><option :value="-1">none</option><option v-for="(r, i) in runs" :key="r.id" :value="i" :disabled="i === idx">{{ r.id }}</option></select></div>
    <div class="grid g3"><div v-for="c in cards" :key="c.t" class="card" :title="c.d"><div class="muted small">{{ c.t }} <span aria-label="definition" :title="c.d">ⓘ</span></div><div style="font-size:20px;font-weight:700">{{ c.v }}</div><div class="muted small">{{ c.d }}</div></div></div>
    <section class="card" style="margin-top:14px"><h2>Run configuration</h2><div class="row"><span class="badge gray">model: fixture</span><span class="badge gray">prompt: prompt-2026.10</span><span class="badge gray">workflow: wf-1.0.0</span><span class="badge gray">retrieval: lexical, top-k {{ cur.config.topK }}</span><span class="badge gray">max retries {{ cur.config.maxRetries }}</span><span class="badge gray">dataset {{ cur.dataset }}</span></div></section>
    <section v-if="prev && psum && sum" class="card" style="margin-top:14px"><h2>Compare {{ cur.id }} vs {{ prev.id }}</h2>
      <div class="tablewrap"><table><thead><tr><th>Metric</th><th>{{ cur.id }}</th><th>{{ prev.id }}</th></tr></thead><tbody>
        <tr><td>Config</td><td class="mono">top-k {{ cur.config.topK }}, retries {{ cur.config.maxRetries }}</td><td class="mono">top-k {{ prev.config.topK }}, retries {{ prev.config.maxRetries }}</td></tr>
        <tr><td>Passed</td><td>{{ sum.pass }}/{{ sum.n }}</td><td>{{ psum.pass }}/{{ psum.n }}</td></tr><tr><td>Citation coverage</td><td>{{ pct(sum.citationCoverage) }}</td><td>{{ pct(psum.citationCoverage) }}</td></tr><tr><td>p95 latency</td><td>{{ sum.p95 }} ms</td><td>{{ psum.p95 }} ms</td></tr>
        <tr><td>Cases that differ</td><td colspan="2">{{ cur.results.filter((r, i) => r.pass !== prev!.results[i]?.pass).map(r => r.caseId).join(', ') || 'none' }}</td></tr></tbody></table></div>
      <p class="muted small">Aggregate numbers alone do not make a configuration “better”; inspect the differing cases.</p></section>
    <div class="filters" style="margin-top:14px"><select v-model="cat" aria-label="Category"><option value="">All categories</option><option v-for="c in cats" :key="c">{{ c }}</option></select></div>
    <div class="tablewrap"><table><thead><tr><th>Case</th><th>Category</th><th>Name</th><th>Expected</th><th>Actual</th><th>Checks</th><th>Latency</th><th>Status</th></tr></thead><tbody>
      <tr v-for="r in rows" :key="r.caseId"><td class="mono">{{ r.caseId }}</td><td>{{ r.category }}</td><td>{{ r.name }}</td><td>{{ r.expected }}</td><td class="small">{{ r.actual }}</td>
        <td><div v-for="k in r.checks" :key="k.name" class="small">{{ k.pass ? '✓' : '✕' }} {{ k.name }}</div></td><td>{{ r.latencyMs }} ms</td><td><Badge :v="r.pass ? 'ok' : 'error'" :label="r.pass ? 'pass' : 'fail'" /></td></tr></tbody></table></div>
  </template>
</template>
