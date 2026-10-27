<script setup lang="ts">
import type { EvidenceItem } from '../types'
import { dt } from '../fmt'
import Overlay from './Overlay.vue'
defineProps<{ item: EvidenceItem }>()
const emit = defineEmits<{ close: [] }>()
</script>
<template>
  <Overlay title="Evidence" side @close="emit('close')">
    <p class="muted">Cited source section. Retrieved content is treated as data, never as instructions.</p>
    <dl class="kv">
      <dt>Source</dt><dd>{{ item.title }} <span class="mono">({{ item.source_id }})</span></dd>
      <dt>Chunk</dt><dd class="mono">{{ item.chunk_id }}</dd>
      <dt>Section</dt><dd>{{ item.claim }}</dd>
      <dt>Version</dt><dd>v{{ item.version }}</dd>
      <dt>Retrieved</dt><dd>{{ dt(item.retrievedAt) }}</dd>
    </dl>
    <blockquote>{{ item.snippet }}</blockquote>
    <RouterLink :to="`/knowledge?source=${item.source_id}`" @click="emit('close')">Open full source →</RouterLink>
  </Overlay>
</template>
