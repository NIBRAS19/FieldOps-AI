import type { Ticket } from './types'
export const dt = (ts?: number) => (ts ? new Date(ts).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—')
export function ago(ts: number) {
  const s = Math.round((Date.now() - ts) / 1000)
  if (s < 0) { const m = Math.round(-s / 60); return m < 120 ? `in ${m}m` : `in ${Math.round(m / 60)}h` }
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}
export function sla(t: Ticket): { band: 'breached' | 'at_risk' | 'ok' | 'done'; label: string } {
  if (t.status === 'resolved' || t.status === 'closed') return { band: 'done', label: 'Met / stopped' }
  const left = t.slaDue - Date.now()
  if (left < 0) return { band: 'breached', label: `Breached ${ago(t.slaDue)}` }
  if (left < 4 * 3600_000) return { band: 'at_risk', label: `Due ${ago(t.slaDue)}` }
  return { band: 'ok', label: `Due ${ago(t.slaDue)}` }
}
export const human = (s: string) => s.replace(/_/g, ' ')
export const KIND: Record<string, string> = {
  open: 'gray', in_progress: 'blue', waiting_info: 'amber', resolved: 'green', closed: 'gray',
  low: 'gray', medium: 'blue', high: 'amber', critical: 'red',
  pending: 'amber', approved: 'blue', rejected: 'red', expired: 'gray', simulated_success: 'green', simulated_failure: 'red',
  ready_for_review: 'amber', blocked: 'red', failed: 'red', cancelled: 'gray', running: 'blue', queued: 'gray', not_started: 'gray',
  ok: 'green', warn: 'amber', error: 'red', success: 'green', denied: 'red', failure: 'red', info: 'gray', active: 'green', inactive: 'gray',
  breached: 'red', at_risk: 'amber', done: 'gray'
}
export const ICON: Record<string, string> = { green: '✓', amber: '!', red: '✕', blue: '●', gray: '○' }
export function download(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url)
}
