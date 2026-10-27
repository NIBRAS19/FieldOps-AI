export type Role = 'admin' | 'lead' | 'agent' | 'readonly'
export type Category = 'access' | 'connectivity' | 'device' | 'application' | 'request' | 'other'
export type Priority = 'low' | 'medium' | 'high' | 'critical'
export type Status = 'open' | 'in_progress' | 'waiting_info' | 'resolved' | 'closed'
export type ActionType = 'assign_ticket' | 'add_internal_note' | 'draft_customer_reply' | 'request_more_information' | 'change_local_status'
export type Risk = 'low' | 'medium' | 'high'
export type Fault = 'none' | 'timeout' | 'malformed' | 'retrieval'
export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'executing' | 'simulated_success' | 'simulated_failure'
export type RunStatus = 'queued' | 'running' | 'ready_for_review' | 'blocked' | 'failed' | 'cancelled'

export interface User { id: string; name: string; role: Role; team: string; active: boolean }
export interface Note { id: string; by: string; ts: number; text: string; kind: 'human' | 'ai_note' | 'reply_draft' | 'info_request' }
export interface Ticket {
  id: string; title: string; description: string; category: Category; priority: Priority; status: Status
  assignee: string | null; team: string; created: number; updated: number; slaDue: number
  asset?: string; customer?: string; synthetic: true; notes: Note[]
}
export interface HistCase { id: string; title: string; category: Category; resolution: string }
export interface Chunk { id: string; section: string; text: string; keywords: string; tags?: string[]; conflictsWith?: string }
export interface KbSource {
  id: string; title: string; type: string; version: number; owner: string
  status: 'active' | 'inactive'; visibility: 'all' | 'admin'; updated: number; chunks: Chunk[]
}
export interface Config { topK: number; maxRetries: number; approvalExpiryMin: number; fault: Fault }
export interface EvidenceItem { source_id: string; chunk_id: string; claim: string; snippet: string; title: string; version: number; retrievedAt: number }
export interface PlanStep { n: number; instruction: string; evidence_ids: string[]; human: boolean }
export interface Output {
  summary: string
  classification: { category: Category; urgency: Priority; confidence: number; rationale: string }
  evidence: EvidenceItem[]; steps: PlanStep[]; draft: string
  limitations: string[]; needsMoreInfo: boolean; proposalIds: string[]
}
export interface RunEvent { step: string; status: 'ok' | 'warn' | 'error' | 'blocked'; ts: number; durationMs: number; detail: string; attempt?: number; sourceIds?: string[] }
export interface Run {
  id: string; ticketId: string; by: string; mode: 'fixture'; workflowVersion: string; promptVersion: string
  config: Config; status: RunStatus; started: number; ended?: number; events: RunEvent[]
  output?: Output; error?: string; label?: 'helpful' | 'partially_helpful' | 'unhelpful'; labelReason?: string; evalSample?: boolean
}
export interface Payload { assignee?: string; team?: string; text?: string; to?: Status }
export interface ProposalDraft { type: ActionType; payload: Payload; summary: string; rationale: string; expectedEffect: string; rollback: string; evidenceIds: string[] }
export interface Proposal extends ProposalDraft {
  id: string; ticketId: string; runId: string; requester: string; risk: Risk; riskReason: string
  status: ProposalStatus; created: number; expires: number; version: number; hash: string
  history: { version: number; payload: Payload; by: string; ts: number; note: string }[]
  decision?: { by: string; at: number; action: 'approve' | 'edit_approve' | 'reject'; reason?: string; comment?: string }
  result?: string
}
export interface AuditEvent {
  id: string; ts: number; actor: string; role: Role | 'system'; action: string; target: string
  result: 'success' | 'denied' | 'failure' | 'info'; detail: string; runId?: string; mode: 'simulated'
}
export interface EvalCheck { name: string; pass: boolean }
export interface EvalResult {
  caseId: string; category: string; name: string; expected: string; actual: string
  checks: EvalCheck[]; pass: boolean; latencyMs: number
  metrics: { citationCoverage: number | null; schemaValid: boolean | null; policyPass: boolean }; providerError: boolean
}
export interface EvalRun { id: string; ts: number; dataset: string; by: string; config: Config; results: EvalResult[] }
export interface State {
  v: number; seq: number; userId: string | null; users: User[]; tickets: Ticket[]; cases: HistCase[]
  kb: KbSource[]; runs: Run[]; proposals: Proposal[]; audit: AuditEvent[]; evalRuns: EvalRun[]
  executed: string[]; config: Config; datasetVersion: number; health: Record<string, number>
}
