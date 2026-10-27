import type { ActionType, Payload, Proposal, Risk, Role, Status, User } from '../types'

export const STATUSES: Status[] = ['open', 'in_progress', 'waiting_info', 'resolved', 'closed']
export const TRANSITIONS: Record<Status, Status[]> = {
  open: ['in_progress', 'waiting_info'],
  in_progress: ['waiting_info', 'resolved'],
  waiting_info: ['in_progress', 'resolved'],
  resolved: ['closed', 'in_progress'],
  closed: []
}

export const ACTIONS: Record<ActionType, { label: string; editable: (keyof Payload)[]; desc: string }> = {
  assign_ticket: { label: 'Assign ticket', editable: ['assignee', 'team'], desc: 'Changes the assignee and team on the local synthetic ticket.' },
  add_internal_note: { label: 'Add internal note', editable: ['text'], desc: 'Writes an internal note to the local ticket record.' },
  draft_customer_reply: { label: 'Draft customer reply', editable: ['text'], desc: 'Stores an approved reply draft locally. Nothing is ever sent.' },
  request_more_information: { label: 'Request more information', editable: ['text'], desc: 'Stores a clarification request and sets the ticket to waiting_info. Nothing is sent.' },
  change_local_status: { label: 'Change ticket status', editable: ['to'], desc: 'Moves the synthetic ticket along a restricted status transition.' }
}
export const ALLOWED_TOOLS = [
  { name: 'search_knowledge', mode: 'Read', approval: false, purpose: 'Search approved internal docs' },
  { name: 'get_related_cases', mode: 'Read', approval: false, purpose: 'Retrieve synthetic historical cases' },
  { name: 'get_asset_context', mode: 'Read', approval: false, purpose: 'Fetch synthetic asset metadata' },
  { name: 'draft_internal_note', mode: 'Propose', approval: true, purpose: 'Create note payload' },
  { name: 'propose_ticket_assignment', mode: 'Propose', approval: true, purpose: 'Suggest assignee/team' },
  { name: 'draft_customer_reply', mode: 'Propose', approval: true, purpose: 'Create draft text; never sends externally' },
  { name: 'request_more_information', mode: 'Propose', approval: true, purpose: 'Draft a clarification request' },
  { name: 'set_local_ticket_status', mode: 'Propose', approval: true, purpose: 'Update synthetic ticket status (restricted transitions)' }
]
export const FORBIDDEN_TOOLS = ['arbitrary shell', 'arbitrary SQL', 'unrestricted web browsing', 'filesystem access', 'credential retrieval', 'real outbound messaging', 'payments / refunds', 'role administration by the agent', 'record deletion']
export const FORBIDDEN_INTENT = /(refund|delete (all |the )?(audit )?(records|tickets|logs)|drop table|rm -rf|run (a )?shell|(reset|reveal|share) .{0,20}(admin )?password|send (an )?email to all)/i
export const INJECTION = /ignore (all |any )?(previous|prior) instructions|disregard .{0,30}(polic|rules)|system prompt|you are now|reveal .{0,25}(secret|key|password)/i

export function riskFor(type: ActionType, p: Payload): { risk: Risk; reason: string } {
  if (type === 'change_local_status' && (p.to === 'resolved' || p.to === 'closed'))
    return { risk: 'high', reason: 'Closing out a ticket removes it from active queues and ends SLA tracking.' }
  if (type === 'assign_ticket' || type === 'change_local_status' || type === 'request_more_information')
    return { risk: 'medium', reason: 'Changes ticket ownership or workflow state in the local record.' }
  return { risk: 'low', reason: 'Adds text only; no ownership or status change.' }
}

export function validatePayload(type: ActionType, p: Payload, users: User[]): string[] {
  const e: string[] = []
  if (!(type in ACTIONS)) return ['Action type is not on the allowlist.']
  if (type === 'assign_ticket') {
    if (!p.assignee || !users.some(u => u.id === p.assignee && u.active)) e.push('Assignee must be an active synthetic user.')
    if (!p.team) e.push('Team is required.')
  } else if (type === 'change_local_status') {
    if (!p.to || !STATUSES.includes(p.to)) e.push('Target status is invalid.')
  } else {
    const t = (p.text ?? '').trim()
    if (t.length < 5) e.push('Text must be at least 5 characters.')
    if (t.length > 1500) e.push('Text must be 1500 characters or fewer.')
    if (INJECTION.test(t)) e.push('Text contains instruction-override patterns and was rejected.')
  }
  return e
}

export function canDecide(role: Role, userId: string, p: Proposal): { ok: boolean; why?: string } {
  if (role === 'readonly') return { ok: false, why: 'Read-only role cannot approve or reject.' }
  if (role === 'agent' && p.risk === 'high' && p.requester === userId) return { ok: false, why: 'You cannot approve your own high-risk proposal.' }
  return { ok: true }
}

export function makeHash(type: string, ticketId: string, payload: Payload, version: number): string {
  const s = JSON.stringify([type, ticketId, payload, version])
  let h = 5381
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0
  return 'h' + (h >>> 0).toString(16).padStart(8, '0')
}
