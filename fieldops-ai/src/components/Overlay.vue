<script setup lang="ts">
defineProps<{ title: string; side?: boolean }>()
const emit = defineEmits<{ close: [] }>()
</script>
<template>
  <div class="scrim" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div class="overlay" :class="{ side }" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
      <header><h3>{{ title }}</h3><button class="ghost" aria-label="Close" @click="emit('close')">✕</button></header>
      <div class="body"><slot /></div>
      <footer v-if="$slots.footer"><slot name="footer" /></footer>
    </div>
  </div>
</template>
