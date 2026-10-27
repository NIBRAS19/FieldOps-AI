import type { Category, Chunk, Config, EvidenceItem, Fault, HistCase, KbSource, Output, PlanStep, Priority, ProposalDraft, Role, RunEvent, Ticket, User } from '../types'
import { DEFAULT_ASSIGNEE, TEAM_BY_CATEGORY } from './seed'
import { FORBIDDEN_INTENT, INJECTION, TRANSITIONS, riskFor, validatePayload } from './policy'

export type EvDraft = Omit<RunEvent, 'ts'>
export interface Ctx { ticket: Ticket; kb: KbSource[]; users: User[]; cases: HistCase[]; role: Role; cfg: Config; fault?: Fault }
export interface Result {
  status: 'ready_for_review' | 'blocked' | 'failed'; events: EvDraft[]; output?: Output
  drafts: ProposalDraft[]; error?: string; retrievedIds: string[]; quarantined: string[]
}

const STOP = new Set('the and for with that this have has had was were are not but you your from into when then than they them their there what which would could should will can may need please after before since about also just very any all our out one two new been being its'.split(' '))
export const tokenize = (s: string) => new Set(s.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').split(/\s+/).filter(w => w.length > 2 && !STOP.has(w)))
export const sanitize = (s: string) => s.replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, '[email]').replace(/\+?\d[\d\s-]{8,}\d/g, '[phone]').slice(0, 4000)

const CAT_WORDS: Record<Category, string> = {
  connectivity: 'vpn wifi wireless network connect connection internet drops',
  access: 'access permission password mfa login authenticator account folder sharepoint',
  device: 'laptop battery charging screen device keyboard boot charger',
  application: 'application app crash crashes software excel license workbook macro',
  request: 'request order monitor hardware hire peripheral',
  other: ''
}
export function classify(text: string): { category: Category; hits: number } {
  const toks = tokenize(text)
  let best: Category = 'other', hits = 0
  for (const c of Object.keys(CAT_WORDS) as Category[]) {
    const n = CAT_WORDS[c].split(' ').filter(w => w && toks.has(w)).length
    if (n > hits) { best = c; hits = n }
  }
  return { category: best, hits }
}

export function search(q: string, kb: KbSource[], role: Role, topK: number) {
  const eligible = kb.filter(s => s.status === 'active' && (s.visibility === 'all' || role === 'admin' || role === 'lead'))
  const qt = tokenize(q)
  const scored: { src: KbSource; chunk: Chunk; score: number }[] = []
  for (const src of eligible) for (const chunk of src.chunks) {
    const ct = tokenize(`${chunk.section} ${chunk.text} ${chunk.keywords}`)
    let score = 0
    qt.forEach(w => { if (ct.has(w)) score++ })
    if (score >= 2) scored.push({ src, chunk, score })
  }
  scored.sort((a, b) => b.score - a.score)
  const top = scored[0]?.score ?? 0
  const picked = scored.filter(s => s.score >= Math.max(2, Math.ceil(top * 0.5))).slice(0, topK)
  return { picked, eligibleSources: eligible.length, excluded: kb.length - eligible.length, candidates: scored.length }
}

export function validateOutput(o: Output, retrieved: Set<string>): string[] {
  const e: string[] = []
  if (!o.summary) e.push('summary missing')
  if (!['access', 'connectivity', 'device', 'application', 'request', 'other'].includes(o.classification?.category)) e.push('classification.category invalid')
  if (!Array.isArray(o.steps)) e.push('steps must be an array')
  o.evidence?.forEach(x => { if (!retrieved.has(x.chunk_id)) e.push(`citation ${x.chunk_id} not in retrieved set`) })
  o.steps?.forEach(s => s.evidence_ids.forEach(id => { if (!retrieved.has(id)) e.push(`step ${s.n} cites unknown ${id}`) }))
  if (typeof o.needsMoreInfo !== 'boolean') e.push('needsMoreInfo missing')
  return e
}

export function runPipeline(ctx: Ctx): Result {
  const { ticket, cfg, role } = ctx
  const events: EvDraft[] = []
  let t0 = performance.now()
  const ev = (step: string, status: EvDraft['status'], detail: string, x: Partial<EvDraft> = {}) => {
    const n = performance.now()
    events.push({ step, status, detail, durationMs: Math.max(1, Math.round(n - t0)), ...x })
    t0 = performance.now()
  }
  const fail = (error: string): Result => ({ status: 'failed', events, drafts: [], error, retrievedIds: [], quarantined: [] })

  // 1. input validation + allowed read-only context
  const text = sanitize(`${ticket.title}. ${ticket.description}`)
  if (!text.trim()) { ev('input_validation', 'error', 'Ticket has no usable text.'); return fail('invalid_input') }
  const related = ctx.cases.filter(c => c.category === ticket.category).length
  ev('input_validation', 'ok', `Ticket ${ticket.id} validated for role "${role}". Fields sanitized. Asset context: ${ticket.asset ? ticket.asset + ' (synthetic record)' : 'none'}. Related synthetic cases: ${related}.`)

  // 2. classification
  const cl = classify(text)
  const urgency: Priority = /outage|all users|production|several (workers|users)/i.test(text) && ticket.priority === 'medium' ? 'high' : ticket.priority
  ev('classification', 'ok', `Rule-based classifier: category "${cl.category}" (${cl.hits} keyword hits), urgency suggestion "${urgency}".`)

  // 3. retrieval
  if (ctx.fault === 'retrieval') {
    ev('retrieval', 'error', 'Evidence service unavailable (simulated fault). No citations were fabricated.')
    return fail('retrieval_unavailable')
  }
  const r = search(text, ctx.kb, role, cfg.topK)
  ev('retrieval', 'ok', `Lexical retrieval, top-k=${cfg.topK}. Access/status filter applied first: ${r.eligibleSources} sources eligible, ${r.excluded} excluded. ${r.candidates} candidate chunks, ${r.picked.length} selected.`, { sourceIds: r.picked.map(p => p.chunk.id) })

  // 4. evidence filter (untrusted content + conflicts)
  const quarantined: string[] = []
  let usable = r.picked.filter(p => {
    if (INJECTION.test(p.chunk.text)) { quarantined.push(p.chunk.id); return false }
    return true
  })
  const limitations: string[] = ['No live endpoint or system check was performed; all context is synthetic.']
  const dropped = new Set<string>()
  for (const p of usable) {
    const other = p.chunk.conflictsWith && usable.find(u => u.chunk.id === p.chunk.conflictsWith)
    if (other) {
      const older = p.src.version < other.src.version ? p : other
      dropped.add(older.chunk.id)
      limitations.push(`Conflicting guidance between ${p.chunk.id} (v${p.src.version}) and ${other.chunk.id} (v${other.src.version}). Newer version preferred; confirm with the ${other.src.owner} owner.`)
    }
  }
  usable = usable.filter(p => !dropped.has(p.chunk.id)).sort((a, b) => a.chunk.id.localeCompare(b.chunk.id))
  const fStatus = quarantined.length || dropped.size ? 'warn' : 'ok'
  ev('evidence_filter', fStatus, `${usable.length} chunks kept. Quarantined as untrusted instructions: ${quarantined.join(', ') || 'none'}. Dropped for version conflict: ${[...dropped].join(', ') || 'none'}.`, { sourceIds: usable.map(u => u.chunk.id) })
  if (quarantined.length) limitations.push(`Untrusted instruction-like content in ${quarantined.join(', ')} was treated as data and excluded.`)

  // 5. plan generation (deterministic fixture model)
  const maxAttempts = cfg.maxRetries + 1
  if (ctx.fault === 'timeout') {
    for (let a = 1; a <= maxAttempts; a++) ev('plan_generation', 'error', `Provider timeout on attempt ${a}/${maxAttempts} (simulated fault).`, { attempt: a })
    return fail('provider_timeout')
  }
  const evidence: EvidenceItem[] = usable.map(u => ({
    source_id: u.src.id, chunk_id: u.chunk.id, claim: u.chunk.section, snippet: u.chunk.text, title: u.src.title, version: u.src.version, retrievedAt: Date.now()
  }))
  const steps: PlanStep[] = usable.map((u, i) => ({ n: i + 1, instruction: u.chunk.text, evidence_ids: [u.chunk.id], human: true }))
  const needsMoreInfo = usable.length === 0
  const forbidden = FORBIDDEN_INTENT.test(text)
  const name = ticket.customer ?? 'there'
  const draft = needsMoreInfo
    ? `Hi ${name},\n\nThanks for contacting IT. To help we need a few details:\n1. What were you trying to do when the problem started?\n2. Any error message or code shown?\n3. Which device or asset tag is affected, and since when?\n\n— Operations team (draft, not sent)`
    : `Hi ${name},\n\nThanks for contacting IT about "${ticket.title}". Here is what we suggest:\n${steps.map(s => `${s.n}. ${s.instruction}`).join('\n')}\n\nIf this does not help, reply on the ticket and we will escalate.\n\n— Operations team (draft, not sent)`
  if (needsMoreInfo) limitations.push('No adequate evidence found. The plan asks for clarification instead of guessing.')
  const output: Output = {
    summary: needsMoreInfo
      ? `${ticket.title}: not enough information or evidence to recommend steps.`
      : `${ticket.title}: classified as ${cl.category}. ${usable.length} supporting source section(s) found; ${steps.length} recommended step(s).`,
    classification: { category: cl.category, urgency, confidence: Math.min(0.9, 0.35 + 0.08 * cl.hits), rationale: `Matched ${cl.hits} ${cl.category} keyword(s) in the ticket text. Confidence is an uncalibrated fixture estimate.` },
    evidence, steps, draft, limitations, needsMoreInfo, proposalIds: []
  }
  const wantMalformed = ctx.fault === 'malformed'
  let malformed: Output | null = wantMalformed ? { ...output, steps: [{ n: 1, instruction: 'x', evidence_ids: ['kb-fake-999-c01'], human: true }] } : null
  ev('plan_generation', 'ok', `Fixture model generated a structured plan (${steps.length} steps, ${evidence.length} citations).`, { attempt: 1 })

  // 6. schema validation (+ one bounded repair)
  const ids = new Set(r.picked.map(p => p.chunk.id))
  const first = malformed ?? output
  const errs = validateOutput(first, ids)
  if (errs.length) {
    ev('schema_validation', 'warn', `Validation failed: ${errs.join('; ')}. Attempting one bounded repair.`, { attempt: 1 })
    const again = validateOutput(output, ids)
    if (again.length) { ev('schema_validation', 'error', 'Repair failed. Returning safe "unable to generate a validated plan" state.', { attempt: 2 }); return fail('schema_invalid') }
    ev('schema_validation', 'ok', 'Repair attempt produced a valid object. Citations verified against the retrieved set.', { attempt: 2 })
  } else ev('schema_validation', 'ok', 'Output is schema-valid. Every citation exists in the retrieved, authorized set.')
  malformed = null

  // 7. policy check + proposals
  const drafts: ProposalDraft[] = []
  const evIds = usable.map(u => u.chunk.id)
  if (forbidden) {
    limitations.push('Request includes operations outside the tool allowlist (refund, deletion, or credential disclosure). No action was proposed; escalate to a human lead.')
    ev('policy_check', 'blocked', 'Blocked: ticket requests operations that are not on the tool allowlist. No proposals created.')
    ev('approval_creation', 'ok', '0 proposals created.')
    ev('completion', 'blocked', 'Run finished as blocked. Ticket not changed.')
    return { status: 'blocked', events, output, drafts, retrievedIds: [...ids], quarantined }
  }
  if (needsMoreInfo) {
    drafts.push({ type: 'request_more_information', payload: { text: draft }, summary: 'Ask the requester for missing details', rationale: 'Evidence was insufficient to recommend steps.', expectedEffect: 'Stores the request locally and sets the ticket to waiting_info. Nothing is sent.', rollback: 'Move the ticket back to in_progress.', evidenceIds: [] })
  } else {
    const noteText = `AI investigation summary: ${output.summary} Evidence: ${evIds.join(', ')}. Human review required.`
    drafts.push({ type: 'add_internal_note', payload: { text: noteText }, summary: 'Save investigation summary as internal note', rationale: 'Keeps the evidence trail with the ticket.', expectedEffect: 'Adds one internal note to the local ticket.', rollback: 'Notes are append-only; add a correcting note.', evidenceIds: evIds })
    drafts.push({ type: 'draft_customer_reply', payload: { text: draft }, summary: 'Store the reply draft for the requester', rationale: 'Draft is built from the cited steps.', expectedEffect: 'Stores an approved draft locally. Not sent.', rollback: 'Replace the draft with a new one.', evidenceIds: evIds })
    const team = TEAM_BY_CATEGORY[cl.category]
    if (cl.category !== 'other' && (!ticket.assignee || ticket.team !== team))
      drafts.push({ type: 'assign_ticket', payload: { assignee: DEFAULT_ASSIGNEE[team], team }, summary: `Assign to ${team}`, rationale: `Category "${cl.category}" is handled by ${team}.`, expectedEffect: 'Updates assignee and team on the local ticket.', rollback: 'Reassign to the previous owner.', evidenceIds: evIds })
    if (ticket.status === 'open') drafts.push({ type: 'change_local_status', payload: { to: 'in_progress' }, summary: 'Move ticket to in_progress', rationale: 'Investigation produced actionable steps.', expectedEffect: 'Status becomes in_progress.', rollback: 'Not reversible through allowed transitions from in_progress back to open.', evidenceIds: evIds })
    if (ticket.status === 'in_progress' && usable.some(u => u.chunk.tags?.includes('resolvable')))
      drafts.push({ type: 'change_local_status', payload: { to: 'resolved' }, summary: 'Move ticket to resolved', rationale: 'A cited procedure says the ticket may be resolved after requester confirmation.', expectedEffect: 'Status becomes resolved and SLA tracking ends.', rollback: 'Reopen by moving resolved to in_progress.', evidenceIds: evIds.filter(id => usable.find(u => u.chunk.id === id)?.chunk.tags?.includes('resolvable')) })
  }
  const kept: ProposalDraft[] = []
  const msgs: string[] = []
  for (const d of drafts) {
    const errs2 = validatePayload(d.type, d.payload, ctx.users)
    if (d.type === 'change_local_status' && d.payload.to && !TRANSITIONS[ticket.status].includes(d.payload.to)) errs2.push(`Transition ${ticket.status} -> ${d.payload.to} is not allowed.`)
    if (errs2.length) msgs.push(`${d.type}: ${errs2.join(' ')}`); else { kept.push(d); }
  }
  ev('policy_check', msgs.length ? 'warn' : 'ok', `${kept.length}/${drafts.length} proposals passed allowlist, schema and transition checks. Risk classes: ${kept.map(k => riskFor(k.type, k.payload).risk).join(', ') || 'n/a'}.${msgs.length ? ' Dropped: ' + msgs.join(' | ') : ''}`)
  ev('approval_creation', 'ok', `${kept.length} pending approval(s) will be created. Nothing is executed without a human decision.`)
  ev('completion', 'ok', 'Investigation complete. This does not mean the ticket is resolved.')
  return { status: 'ready_for_review', events, output, drafts: kept, retrievedIds: [...ids], quarantined }
}
