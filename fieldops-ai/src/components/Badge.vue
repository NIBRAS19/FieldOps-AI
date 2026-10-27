<script setup lang="ts">
import { computed } from 'vue'
import { ICON, KIND, human } from '../fmt'
const props = defineProps<{ v: string; label?: string }>()
const kind = computed(() => KIND[props.v] ?? 'gray')
</script>
<template><span class="badge" :class="kind"><span aria-hidden="true">{{ ICON[kind] }}</span> {{ label ?? human(v) }}</span></template>
