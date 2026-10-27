import { reactive, watch } from 'vue'
import { Engine, STORE_KEY, loadState } from './mock/engine'

export const engine = reactive(new Engine(loadState())) as Engine

let timer: number | undefined
watch(() => engine.state, () => {
  clearTimeout(timer)
  timer = window.setTimeout(() => { try { localStorage.setItem(STORE_KEY, JSON.stringify(engine.state)) } catch { /* storage full or blocked */ } }, 250)
}, { deep: true })
setInterval(() => engine.sweepExpired(), 15_000)
