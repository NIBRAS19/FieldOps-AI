import type { ActionType, Category, Priority, Risk, Role } from '../types'

// Backend Ticket Statuses
export type BackendTicketStatus = 'new' | 'assigned' | 'in_progress' | 'awaiting_information' | 'resolved' | 'closed'

export interface BackendUser {
  id: string
  display_name: string
  role: Role
  email?: string
  team?: string | null
}

export interface BackendTicket {
  id: string
  display_id: string
  title: string
  description: string
  category: Category
  priority: Priority
  status: BackendTicketStatus
  assignee_id: string | null
  assignee_name?: string | null
  team_id: string | null
  team_name: string | null
  customer_alias?: string | null
  asset_tag?: string | null
  sla_due_at: string | null
  sla_band: 'ok' | 'at_risk' | 'breached' | 'done'
  ai_state: string
  synthetic: boolean
  version: number
  created_at: string
  updated_at: string
  notes?: BackendNote[]
  related_cases?: { display_id: string; title: string; resolution: string }[]
}

export interface BackendNote {
  id: string
  event_type: string
  actor_id: string | null
  actor_name: string
  payload: { text?: string; from?: string; to?: string; title?: string }
  created_at: string
}

export interface BackendProposal {
  id: string
  display_id?: string
  ticket_id: string
  ticket_display_id?: string
  run_id: string
  action_type: ActionType
  risk_class: Risk
  risk_reason: string
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'executing' | 'simulated_success' | 'simulated_failure'
  payload: Record<string, unknown>
  payload_hash: string
  version: number
  summary: string
  rationale: string
  expected_effect: string
  rollback_note: string
  evidence_ids: string[]
  created_at: string
  expires_at: string
  requester_id?: string
  proposed_by?: string
  proposed_by_name?: string
  decision?: {
    by: string
    actor_name?: string
    at: string
    action: 'approve' | 'edit_approve' | 'reject'
    reason?: string
    comment?: string
  } | null
  execution_result?: string | null
  history?: {
    version: number
    payload: Record<string, unknown>
    by: string
    ts: string
    note: string
  }[]
}

export interface BackendRunEvent {
  sequence_no: number
  step: string
  status: 'ok' | 'warn' | 'error' | 'blocked'
  duration_ms: number
  detail: string
  attempt?: number
  source_ids?: string[]
  error_code?: string | null
  created_at: string
}

export interface BackendRun {
  id: string
  ticket_id: string
  ticket_display_id: string
  started_by: string
  status: 'queued' | 'running' | 'ready_for_review' | 'blocked' | 'failed' | 'cancelled'
  disposition: string
  model_provider: string
  model_name: string
  prompt_version: string
  workflow_version: string
  retrieval_config: { top_k: number }
  error_code?: string | null
  error_summary?: string | null
  label?: 'helpful' | 'partially_helpful' | 'unhelpful' | null
  label_reason?: string | null
  eval_sample?: boolean
  started_at: string
  finished_at?: string | null
  duration_ms?: number | null
  token_usage?: { prompt_tokens: number; completion_tokens: number } | null
  cost_estimate?: number | null
  proposal_ids?: string[]
  output?: {
    summary: string
    classification: { category: Category; urgency: Priority; confidence: number; rationale: string }
    evidence: {
      source_id: string
      chunk_id: string
      claim_supported?: string
      snippet: string
      title: string
      source_version: number
      retrieved_at: string
    }[]
    steps: { n: number; instruction: string; evidence_ids: string[]; requires_human_action?: boolean }[]
    draft: string
    limitations: string[]
    needs_more_info?: boolean
    proposals?: unknown[]
  } | null
}

export interface BackendSource {
  id: string
  source_key: string
  title: string
  source_type: string
  current_version: number
  owner: string
  status: 'active' | 'inactive'
  visibility: 'all' | 'admin'
  updated_at: string
  chunks?: { id: string; chunk_key?: string; section: string; text: string; keywords?: string }[]
}

export interface BackendAuditEvent {
  id: string
  created_at: string
  actor_type: string
  actor_id: string
  actor_name: string
  actor_role: Role | null
  event_type: string
  target_type: string
  target_id: string
  result: 'success' | 'denied' | 'failure' | 'info'
  before?: Record<string, unknown> | null
  after?: Record<string, unknown> | null
  reason?: string | null
  run_id?: string | null
  correlation_id?: string | null
  simulated: boolean
}

export interface BackendConfig {
  top_k: number
  max_retries: number
  approval_expiry_minutes: number
  fault: string
}
