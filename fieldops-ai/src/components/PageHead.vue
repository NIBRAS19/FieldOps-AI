<script setup lang="ts">
defineProps<{ title: string; sub?: string }>()
</script>
<template>
  <div class="pagehead">
    <div><h1>{{ title }}</h1><p v-if="sub" class="muted">{{ sub }}</p></div>
    <div class="actions"><slot /></div>
  </div>
</template>
