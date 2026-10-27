<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { engine } from '../store'
import { ago } from '../fmt'
import { INJECTION } from '../mock/policy'
import Badge from '../components/Badge.vue'
import Overlay from '../components/Overlay.vue'
import PageHead from '../components/PageHead.vue'
const route = useRoute()
const sel = ref<string | null>((route.query.source as string) ?? null)
const src = computed(() => engine.state.kb.find(s => s.id === sel.value))
const q = ref(''), results = ref<ReturnType<typeof engine.testQuery>>([])
const add = ref(false), title = ref(''), text = ref('')
const refs = computed(() => engine.state.runs.filter(r => r.output?.evidence.some(e => e.source_id === sel.value)).length)
const run = () => { results.value = engine.testQuery(q.value) }
const save = () => engine.attempt(async () => { await engine.addSource(title.value, text.value); add.value = false; title.value = text.value = '' })
</script>
<template>
  <PageHead title="Knowledge Library" sub="Seeded synthetic sources used for retrieval. Source content is data, never instructions.">
    <button :disabled="engine.role !== 'admin'" @click="add = true">+ Add manual text source</button></PageHead>
  <div class="tablewrap"><table>
    <thead><tr><th>Title</th><th>Type</th><th>Version</th><th>Owner</th><th>Status</th><th>Visibility</th><th>Chunks</th><th>Updated</th></tr></thead>
    <tbody><tr v-for="s in engine.state.kb" :key="s.id" class="click" tabindex="0" @click="sel = s.id" @keydown.enter="sel = s.id">
      <td><strong>{{ s.title }}</strong><div class="mono muted">{{ s.id }}</div></td><td>{{ s.type }}</td><td>v{{ s.version }}</td><td>{{ s.owner }}</td><td><Badge :v="s.status" /></td><td>{{ s.visibility === 'admin' ? 'admins & leads' : 'all roles' }}</td><td>{{ s.chunks.length }}</td><td class="muted">{{ ago(s.updated) }}</td></tr></tbody></table></div>
  <section class="card" style="margin-top:14px"><h2>Test a retrieval query <span class="muted small">(runs as {{ engine.user.role }})</span></h2>
    <div class="row"><input v-model="q" placeholder="e.g. vpn password rejected" style="flex:1" @keydown.enter="run" aria-label="Test query" /><button class="primary" @click="run">Search</button></div>
    <p v-if="q && !results.length" class="muted">No chunks scored above the relevance threshold. Inactive and restricted sources are excluded before scoring.</p>
    <div v-for="r in results" :key="r.chunk.id" class="note"><small>{{ r.src.title }} · {{ r.chunk.id }} · score {{ r.score }}</small>{{ r.chunk.text }} <Badge v-if="INJECTION.test(r.chunk.text)" v="red" label="would be quarantined" /></div></section>
  <Overlay v-if="src" :title="src.title" side @close="sel = null">
    <dl class="kv"><dt>ID</dt><dd class="mono">{{ src.id }}</dd><dt>Version</dt><dd>v{{ src.version }}</dd><dt>Status</dt><dd><Badge :v="src.status" /></dd><dt>Access scope</dt><dd>{{ src.visibility === 'admin' ? 'Admins & leads only' : 'All roles' }}</dd><dt>Indexing</dt><dd>Lexical index, {{ src.chunks.length }} chunks</dd><dt>Cited in runs</dt><dd>{{ refs }}</dd></dl>
    <div class="row" style="margin:10px 0"><button :disabled="engine.role !== 'admin'" @click="engine.attempt(async () => { await engine.toggleSource(src!.id) })">{{ src.status === 'active' ? 'Deactivate' : 'Activate' }}</button><button :disabled="!['admin', 'lead'].includes(engine.role)" @click="engine.attempt(async () => { await engine.reindex(src!.id) })">Re-index</button></div>
    <p class="muted small">Deactivation stops new retrieval but keeps citation history for earlier runs.</p>
    <h3>Chunks</h3><div v-for="c in src.chunks" :key="c.id" class="note"><small>{{ c.id }} · {{ c.section }}{{ c.tags?.length ? ' · tags: ' + c.tags.join(',') : '' }}{{ c.conflictsWith ? ' · conflicts with ' + c.conflictsWith : '' }}</small>{{ c.text }}
      <div v-if="INJECTION.test(c.text)"><Badge v="red" label="contains instruction-like text — quarantined at retrieval" /></div></div>
  </Overlay>
  <Overlay v-if="add" title="Add manual text source" @close="add = false">
    <p class="muted">Separate chunks with a blank line. Content is treated as potentially adversarial data.</p>
    <label>Title</label><input v-model="title" style="width:100%" /><label>Text</label><textarea v-model="text" />
    <template #footer><button @click="add = false">Cancel</button><button class="primary" @click="save">Add source</button></template></Overlay>
</template>
