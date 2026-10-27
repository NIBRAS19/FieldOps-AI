import type {
  AuditEvent,
  Category,
  Config,
  KbSource,
  Note,
  Output,
  Payload,
  Priority,
  Proposal,
  Risk,
  Role,
  Run,
  RunEvent,
  RunStatus,
  Status,
  Ticket,
  User
} from '../types'
import type {
  BackendAuditEvent,
  BackendConfig,
  BackendNote,
  BackendProposal,
  BackendRun,
  BackendRunEvent,
  BackendSource,
  BackendTicket,
  BackendTicketStatus,
  BackendUser
} from './types'

export function parseDate(iso: string | null | undefined): number {
  if (!iso) return Date.now()
  const d = new Date(iso).getTime()
  return isNaN(d) ? Date.now() : d
}

export function toFrontendStatus(backendStatus: BackendTicketStatus | string): Status {
  switch (backendStatus) {
    case 'new':
    case 'assigned':
      return 'open'
    case 'in_progress':
      return 'in_progress'
    case 'awaiting_information':
      return 'waiting_info'
    case 'resolved':
      return 'resolved'
    case 'closed':
      return 'closed'
    default:
      return 'open'
  }
}

export function toBackendStatus(frontendStatus: Status): BackendTicketStatus {
  switch (frontendStatus) {
    case 'open':
      return 'new'
    case 'in_progress':
      return 'in_progress'
    case 'waiting_info':
      return 'awaiting_information'
    case 'resolved':
      return 'resolved'
    case 'closed':
      return 'closed'
  }
}

export function mapBackendUser(u: BackendUser): User {
  return {
    id: u.id,
    name: u.display_name,
    role: u.role,
    team: u.team || '',
    active: true
  }
}

export function mapBackendNote(n: BackendNote): Note {
  let kind: Note['kind'] = 'human'
  if (n.event_type === 'ai_note') kind = 'ai_note'
  else if (n.event_type === 'reply_draft') kind = 'reply_draft'
  else if (n.event_type === 'info_request') kind = 'info_request'

  return {
    id: n.id,
    by: n.actor_id ?? 'u-system',
    ts: parseDate(n.created_at),
    text: n.payload?.text ?? (n.payload?.title ? `Created ticket: ${n.payload.title}` : n.event_type),
    kind
  }
}

export function mapBackendTicket(bt: BackendTicket, rawEvents?: BackendNote[]): Ticket {
  const notes: Note[] = (rawEvents ?? bt.notes ?? []).map(mapBackendNote)

  return {
    id: bt.display_id || bt.id,
    title: bt.title,
    description: bt.description,
    category: bt.category,
    priority: bt.priority,
    status: toFrontendStatus(bt.status),
    assignee: bt.assignee_id,
    team: bt.team_name || 'Service Desk',
    created: parseDate(bt.created_at),
    updated: parseDate(bt.updated_at),
    slaDue: parseDate(bt.sla_due_at),
    asset: bt.asset_tag || undefined,
    customer: bt.customer_alias || undefined,
    synthetic: true,
    notes
  }
}

export function mapBackendProposal(bp: BackendProposal): Proposal {
  const history = (bp.history ?? []).map(h => ({
    version: h.version,
    payload: (h.payload ?? {}) as Payload,
    by: h.by,
    ts: parseDate(h.ts),
    note: h.note
  }))

  const decision = bp.decision
    ? {
        by: bp.decision.by,
        at: parseDate(bp.decision.at),
        action: bp.decision.action,
        reason: bp.decision.reason,
        comment: bp.decision.comment
      }
    : undefined

  return {
    id: bp.id,
    ticketId: bp.ticket_display_id || bp.ticket_id,
    runId: bp.run_id,
    requester: bp.proposed_by || bp.requester_id || 'u-agent',
    type: bp.action_type,
    payload: (bp.payload ?? {}) as Payload,
    summary: bp.summary,
    rationale: bp.rationale,
    expectedEffect: bp.expected_effect,
    rollback: bp.rollback_note,
    evidenceIds: bp.evidence_ids ?? [],
    risk: bp.risk_class,
    riskReason: bp.risk_reason,
    status: bp.status,
    created: parseDate(bp.created_at),
    expires: parseDate(bp.expires_at),
    version: bp.version,
    hash: bp.payload_hash,
    history,
    decision,
    result: bp.execution_result || undefined
  }
}

export function mapBackendRunEvent(be: BackendRunEvent): RunEvent {
  return {
    step: be.step,
    status: be.status,
    ts: parseDate(be.created_at),
    durationMs: be.duration_ms,
    detail: be.detail || '',
    attempt: be.attempt,
    sourceIds: be.source_ids
  }
}

export function mapBackendRun(br: BackendRun, events?: BackendRunEvent[]): Run {
  let output: Output | undefined
  if (br.output) {
    output = {
      summary: br.output.summary,
      classification: br.output.classification,
      evidence: (br.output.evidence ?? []).map(e => ({
        source_id: e.source_id,
        chunk_id: e.chunk_id,
        claim: e.claim_supported || '',
        snippet: e.snippet,
        title: e.title,
        version: e.source_version,
        retrievedAt: parseDate(e.retrieved_at)
      })),
      steps: (br.output.steps ?? []).map(s => ({
        n: s.n,
        instruction: s.instruction,
        evidence_ids: s.evidence_ids ?? [],
        human: s.requires_human_action ?? true
      })),
      draft: br.output.draft,
      limitations: br.output.limitations ?? [],
      needsMoreInfo: br.output.needs_more_info ?? false,
      proposalIds: br.proposal_ids ?? []
    }
  }

  return {
    id: br.id,
    ticketId: br.ticket_display_id || br.ticket_id,
    by: br.started_by,
    mode: 'fixture',
    workflowVersion: br.workflow_version || 'wf-1.0.0',
    promptVersion: br.prompt_version || 'prompt-2026.10',
    config: {
      topK: br.retrieval_config?.top_k ?? 4,
      maxRetries: 2,
      approvalExpiryMin: 30,
      fault: 'none'
    },
    status: br.status as RunStatus,
    started: parseDate(br.started_at),
    ended: br.finished_at ? parseDate(br.finished_at) : undefined,
    events: (events ?? []).map(mapBackendRunEvent),
    output,
    error: br.error_summary || br.error_code || undefined,
    label: br.label ?? undefined,
    labelReason: br.label_reason ?? undefined,
    evalSample: br.eval_sample
  }
}

export function mapBackendSource(bs: BackendSource): KbSource {
  return {
    id: bs.source_key || bs.id,
    title: bs.title,
    type: bs.source_type,
    version: bs.current_version,
    owner: bs.owner,
    status: bs.status,
    visibility: bs.visibility,
    updated: parseDate(bs.updated_at),
    chunks: (bs.chunks ?? []).map(c => ({
      id: c.chunk_key || c.id,
      section: c.section,
      text: c.text,
      keywords: c.keywords || ''
    }))
  }
}

export function mapBackendAuditEvent(ba: BackendAuditEvent): AuditEvent {
  return {
    id: ba.id,
    ts: parseDate(ba.created_at),
    actor: ba.actor_name || ba.actor_id,
    role: (ba.actor_role as Role) || 'system',
    action: ba.event_type,
    target: ba.target_id,
    result: ba.result,
    detail: ba.reason || (ba.after ? JSON.stringify(ba.after) : ba.event_type),
    runId: ba.run_id || undefined,
    mode: 'simulated'
  }
}

export function mapBackendConfig(bc: BackendConfig): Config {
  return {
    topK: bc.top_k,
    maxRetries: bc.max_retries,
    approvalExpiryMin: bc.approval_expiry_minutes,
    fault: (bc.fault as Config['fault']) || 'none'
  }
}
