import type { ActionType, AuditEvent, Category, Payload, Priority, Proposal, Role, Run, RunStatus, State, Status, Ticket, User } from '../types'
import { makeSeed, TEAM_BY_CATEGORY } from './seed'
import { ACTIONS, TRANSITIONS, canDecide, makeHash, riskFor, validatePayload } from './policy'
import { runPipeline, search } from './pipeline'
import { api } from '../api/client'
import {
  mapBackendAuditEvent,
  mapBackendConfig,
  mapBackendNote,
  mapBackendProposal,
  mapBackendRun,
  mapBackendRunEvent,
  mapBackendSource,
  mapBackendTicket,
  mapBackendUser
} from '../api/mapper'
import type { BackendConfig, BackendProposal } from '../api/types'

export const STORE_KEY = 'fieldops-ai-demo-v1'
export const MODE_KEY = 'fieldops-engine-mode'
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))

export function loadState(): State {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (raw) {
      const s = JSON.parse(raw) as State
      if (s.v === 1) {
        // recover interrupted runs (Workflow E)
        s.runs.forEach(r => {
          if (r.status === 'running' || r.status === 'queued') {
            r.status = 'failed'
            r.error = 'interrupted'
            r.ended = Date.now()
          }
        })
        return s
      }
    }
  } catch {
    /* fall through to seed */
  }
  return makeSeed()
}

export class Engine {
  state: State
  toasts: { id: number; kind: 'ok' | 'error' | 'info'; msg: string }[] = []
  mode: 'live' | 'mock' = 'mock'
  backendOnline = false
  isSyncing = false
  private tid = 0

  constructor(state: State) {
    this.state = state
    const savedMode = localStorage.getItem(MODE_KEY)
    this.mode = savedMode === 'mock' ? 'mock' : 'live'
    void this.initBackendConnection()
  }

  private async initBackendConnection() {
    const online = await api.checkLive()
    this.backendOnline = online
    if (online) {
      if (this.mode === 'live') {
        await this.syncFromBackend()
      }
    } else if (this.mode === 'live') {
      // Auto-fallback to mock if backend is down on startup
      this.toast('Backend is not running at localhost:8000. Operating in Local Mock mode.', 'info')
      this.mode = 'mock'
    }

    // Periodic heartbeat
    setInterval(async () => {
      const isUp = await api.checkLive()
      if (this.backendOnline !== isUp) {
        this.backendOnline = isUp
        if (isUp && this.mode === 'live') {
          void this.syncFromBackend()
        }
      }
    }, 12_000)
  }

  async toggleMode() {
    const next = this.mode === 'live' ? 'mock' : 'live'
    await this.setMode(next)
  }

  async setMode(mode: 'live' | 'mock') {
    this.mode = mode
    localStorage.setItem(MODE_KEY, mode)
    if (mode === 'live') {
      const online = await api.checkLive()
      this.backendOnline = online
      if (online) {
        await this.syncFromBackend()
        this.toast('Switched to Live API Mode (connected to FastAPI backend)', 'ok')
      } else {
        this.toast('FastAPI backend offline at localhost:8000. Start backend server first.', 'error')
        this.mode = 'mock'
        localStorage.setItem(MODE_KEY, 'mock')
      }
    } else {
      this.toast('Switched to Local Mock Mode', 'info')
    }
  }

  async syncFromBackend() {
    if (this.isSyncing) return
    this.isSyncing = true
    try {
      // 1. Users
      const uRes = await api.getDemoUsers()
      if (uRes.users?.length) {
        this.state.users = uRes.users.map(mapBackendUser)
      }

      // 2. Auth / me
      if (api.token) {
        try {
          const me = await api.me()
          if (me?.id) this.state.userId = me.id
        } catch {
          // Token expired or invalid
          api.setToken(null, null)
        }
      }

      // Ensure a default user is selected
      if (!this.state.userId && this.state.users.length) {
        const lead = this.state.users.find(u => u.role === 'lead') || this.state.users[0]
        try {
          await api.demoLogin(lead.id)
          this.state.userId = lead.id
        } catch {
          this.state.userId = lead.id
        }
      }

      // 3. Tickets
      const tRes = await api.listTickets({ page: 1, page_size: 100 })
      if (tRes.items) {
        this.state.tickets = tRes.items.map(bt => mapBackendTicket(bt))
      }

      // 4. Proposals
      const pRes = await api.listProposals()
      if (pRes.items) {
        this.state.proposals = pRes.items.map(bp => mapBackendProposal(bp))
      }

      // 5. Investigations
      const rRes = await api.listInvestigations()
      if (rRes.items) {
        this.state.runs = rRes.items.map(br => mapBackendRun(br))
      }

      // 6. Knowledge Sources
      const kRes = await api.listKnowledgeSources()
      if (kRes.items) {
        this.state.kb = kRes.items.map(bs => mapBackendSource(bs))
      }

      // 7. Audit Events
      const aRes = await api.listAuditEvents({ page_size: 100 })
      if (aRes.items) {
        this.state.audit = aRes.items.map(ba => mapBackendAuditEvent(ba))
      }

      // 8. Admin Config
      try {
        const cfg = await api.getAdminConfig()
        this.state.config = mapBackendConfig(cfg)
      } catch {
        /* Non-admin roles will 403 on admin/config */
      }
    } catch (e) {
      console.warn('Backend sync warning:', e)
    } finally {
      this.isSyncing = false
    }
  }

  // ---------- helpers ----------
  get user(): User {
    return this.state.users.find(u => u.id === this.state.userId) ?? this.state.users[0]
  }

  get role(): Role {
    return this.user.role
  }

  userName(id: string | null | undefined) {
    return id ? this.state.users.find(u => u.id === id)?.name ?? id : 'Unassigned'
  }

  private nid(p: string) {
    return `${p}-${++this.state.seq}`
  }

  toast(msg: string, kind: 'ok' | 'error' | 'info' = 'info') {
    const id = ++this.tid
    this.toasts.push({ id, kind, msg })
    setTimeout(() => {
      this.toasts = this.toasts.filter(t => t.id !== id)
    }, 4500)
  }

  attempt<T>(fn: () => T | Promise<T>): T | Promise<T> | undefined {
    try {
      const res = fn()
      if (res instanceof Promise) {
        return res.catch((e: Error) => {
          this.toast(e.message || 'Operation failed', 'error')
          throw e
        }) as unknown as T
      }
      return res
    } catch (e) {
      this.toast((e as Error).message || 'Operation failed', 'error')
      return undefined
    }
  }

  audit(action: string, target: string, result: AuditEvent['result'], detail: string, runId?: string, actor?: User) {
    const u = actor ?? this.user
    this.state.audit.unshift({
      id: this.nid('aud'),
      ts: Date.now(),
      actor: u?.id ?? 'system',
      role: u?.role ?? 'system',
      action,
      target,
      result,
      detail,
      runId,
      mode: 'simulated'
    })
  }

  private need(ok: boolean, msg: string, action: string, target: string) {
    if (!ok) {
      this.audit(action, target, 'denied', msg)
      throw new Error(msg)
    }
  }

  ticket(id: string) {
    return this.state.tickets.find(t => t.id === id || t.id.toUpperCase() === id.toUpperCase())
  }

  run(id: string) {
    return this.state.runs.find(r => r.id === id)
  }

  proposal(id: string) {
    return this.state.proposals.find(p => p.id === id)
  }

  runsFor(ticketId: string) {
    return this.state.runs
      .filter(r => r.ticketId === ticketId || r.ticketId.toUpperCase() === ticketId.toUpperCase())
      .sort((a, b) => b.started - a.started)
  }

  aiState(ticketId: string): string {
    const r = this.runsFor(ticketId)[0]
    return r ? r.status : 'not_started'
  }

  pending() {
    return this.state.proposals.filter(p => p.status === 'pending')
  }

  // ---------- session ----------
  async login(userId: string) {
    this.state.userId = userId
    if (this.mode === 'live') {
      try {
        await api.demoLogin(userId)
        await this.syncFromBackend()
      } catch (e) {
        this.toast(`Live login warning: ${(e as Error).message}`, 'info')
      }
    }
    this.audit('demo_login', userId, 'info', 'Simulated demo access. This is not identity verification.')
  }

  logout() {
    this.state.userId = null
    if (this.mode === 'live') {
      api.logout()
    }
  }

  async switchRole(userId: string) {
    const from = this.user
    this.state.userId = userId
    if (this.mode === 'live') {
      try {
        await api.demoLogin(userId)
        await this.syncFromBackend()
      } catch (e) {
        this.toast(`Live switch warning: ${(e as Error).message}`, 'info')
      }
    }
    this.audit(
      'simulated_role_switch',
      userId,
      'info',
      `Simulated role switch ${from.role} -> ${this.user.role}. Demo only; not a security mechanism.`
    )
  }

  // ---------- tickets ----------
  async createTicket(d: {
    title: string
    description: string
    category: Category
    priority: Priority
    asset?: string
    customer?: string
  }): Promise<Ticket> {
    this.need(this.role !== 'readonly', 'Read-only role cannot create tickets.', 'ticket_create', 'new')
    if (d.title.trim().length < 5 || d.description.trim().length < 10) {
      throw new Error('Title (5+) and description (10+ characters) are required.')
    }

    if (this.mode === 'live') {
      const bt = await api.createTicket({
        title: d.title,
        description: d.description,
        category: d.category,
        priority: d.priority,
        asset_tag: d.asset || undefined,
        customer_alias: d.customer || undefined
      })
      const mapped = mapBackendTicket(bt)
      this.state.tickets.unshift(mapped)
      this.audit('ticket_created', mapped.id, 'success', 'Synthetic ticket created on FastAPI backend.')
      return mapped
    }

    const n = this.state.tickets.reduce((m, t) => Math.max(m, +t.id.slice(3)), 1000) + 1
    const now = Date.now()
    const slaH = { low: 48, medium: 24, high: 8, critical: 4 }[d.priority]
    const t: Ticket = {
      id: `FO-${n}`,
      ...d,
      status: 'open',
      assignee: null,
      team: TEAM_BY_CATEGORY[d.category],
      created: now,
      updated: now,
      slaDue: now + slaH * 3600_000,
      synthetic: true,
      notes: []
    }
    this.state.tickets.unshift(t)
    this.audit('ticket_created', t.id, 'success', 'Synthetic ticket created.')
    return t
  }

  async addNote(ticketId: string, text: string) {
    this.need(this.role !== 'readonly', 'Read-only role cannot add notes.', 'note_add', ticketId)
    const t = this.ticket(ticketId)
    if (!t) throw new Error('Ticket not found.')
    if (text.trim().length < 3) throw new Error('Note is too short.')

    if (this.mode === 'live') {
      await api.addNote(ticketId, text.trim())
      const evs = await api.getTicketEvents(ticketId)
      t.notes = evs.items.map(mapBackendNote)
      t.updated = Date.now()
      this.audit('note_added', ticketId, 'success', 'Human note added via FastAPI backend.')
      return
    }

    t.notes.push({ id: this.nid('note'), by: this.user.id, ts: Date.now(), text: text.trim(), kind: 'human' })
    t.updated = Date.now()
    this.audit('note_added', ticketId, 'success', 'Human note added.')
  }

  async assignDirect(ticketId: string, assignee: string | null) {
    this.need(this.role !== 'readonly', 'Read-only role cannot assign tickets.', 'ticket_assign', ticketId)
    const t = this.ticket(ticketId)
    if (!t) throw new Error('Ticket not found.')
    const prev = t.assignee

    if (this.mode === 'live') {
      await api.assign(ticketId, assignee)
      t.assignee = assignee
      t.updated = Date.now()
      this.audit(
        'ticket_assigned',
        ticketId,
        'success',
        `Assignee ${this.userName(prev)} -> ${this.userName(assignee)} (FastAPI backend record).`
      )
      return
    }

    t.assignee = assignee
    t.updated = Date.now()
    this.audit(
      'ticket_assigned',
      ticketId,
      'success',
      `Assignee ${this.userName(prev)} -> ${this.userName(assignee)} (manual, local record).`
    )
  }

  // ---------- investigations ----------
  async investigate(ticketId: string): Promise<Run> {
    this.need(this.role !== 'readonly', 'Read-only role cannot start investigations.', 'investigation_start', ticketId)
    const t = this.ticket(ticketId)
    if (!t) throw new Error('Ticket not found.')
    const recent = this.state.runs.filter(r => r.by === this.user.id && Date.now() - r.started < 60_000).length
    this.need(recent < 5, 'Rate limit: at most 5 investigations per minute.', 'investigation_start', ticketId)
    const user = this.user

    // LIVE BACKEND MODE
    if (this.mode === 'live') {
      const runSummary = await api.startInvestigation(ticketId, { mode: 'fixture' })
      const run: Run = {
        id: runSummary.id,
        ticketId,
        by: user.id,
        mode: 'fixture',
        workflowVersion: runSummary.workflow_version || 'wf-1.0.0',
        promptVersion: runSummary.prompt_version || 'prompt-2026.10',
        config: { ...this.state.config },
        status: 'queued',
        started: Date.now(),
        events: []
      }
      this.state.runs.unshift(run)
      this.audit('investigation_started', ticketId, 'success', `Run ${run.id} started on FastAPI backend.`, run.id)

      // Progressive polling for events
      let attempts = 0
      while (attempts < 60) {
        await sleep(350)
        attempts++
        try {
          const evRes = await api.getInvestigationEvents(run.id)
          run.events = evRes.items.map(mapBackendRunEvent)
          run.status = evRes.run_status as RunStatus

          if (['ready_for_review', 'blocked', 'failed', 'cancelled'].includes(run.status)) {
            const full = await api.getInvestigation(run.id)
            const mapped = mapBackendRun(full, evRes.items)
            Object.assign(run, mapped)

            // Refresh proposals for this ticket
            const pRes = await api.listProposals({ ticket_id: ticketId })
            if (pRes.items) {
              const mappedProps = pRes.items.map(mapBackendProposal)
              mappedProps.forEach(mp => {
                const idx = this.state.proposals.findIndex(p => p.id === mp.id)
                if (idx >= 0) this.state.proposals[idx] = mp
                else this.state.proposals.unshift(mp)
              })
            }

            // Refresh ticket
            const tUpdated = await api.getTicket(ticketId)
            const tLocal = this.ticket(ticketId)
            if (tLocal) Object.assign(tLocal, mapBackendTicket(tUpdated))

            this.toast(
              `Investigation finished: ${run.status === 'ready_for_review' ? 'Ready for review' : run.status}`,
              run.status === 'failed' ? 'error' : 'ok'
            )
            this.audit(
              'investigation_finished',
              ticketId,
              run.status === 'failed' ? 'failure' : 'success',
              `Run ${run.id} ended as ${run.status}.`,
              run.id
            )
            break
          }
        } catch (e) {
          console.warn('Polling error:', e)
        }
      }
      return run
    }

    // LOCAL MOCK MODE
    const run: Run = {
      id: this.nid('run'),
      ticketId,
      by: user.id,
      mode: 'fixture',
      workflowVersion: 'wf-1.0.0',
      promptVersion: 'prompt-2026.10',
      config: { ...this.state.config },
      status: 'queued',
      started: Date.now(),
      events: []
    }
    this.state.runs.unshift(run)
    this.audit(
      'investigation_started',
      ticketId,
      'success',
      `Run ${run.id} started in fixture mode${run.config.fault !== 'none' ? ` with simulated fault "${run.config.fault}"` : ''}.`,
      run.id
    )
    const live = this.run(run.id)!
    const res = runPipeline({
      ticket: JSON.parse(JSON.stringify(t)),
      kb: JSON.parse(JSON.stringify(this.state.kb)),
      users: this.state.users,
      cases: this.state.cases,
      role: user.role,
      cfg: run.config,
      fault: run.config.fault
    })
    live.status = 'running'
    for (const e of res.events) {
      await sleep(320)
      if ((live.status as string) === 'cancelled') return live
      live.events.push({ ...e, ts: Date.now() })
    }
    await sleep(200)
    if ((live.status as string) === 'cancelled') return live
    live.ended = Date.now()
    live.status = res.status
    live.error = res.error
    if (res.output) {
      live.output = res.output
      // supersede older pending proposals for this ticket
      this.state.proposals
        .filter(p => p.ticketId === ticketId && p.status === 'pending')
        .forEach(p => {
          p.status = 'expired'
          this.audit('proposal_superseded', p.id, 'info', `Superseded by run ${run.id}.`, run.id)
        })
      for (const d of res.drafts) {
        const { risk, reason } = riskFor(d.type, d.payload)
        const id = this.nid('prop')
        this.state.proposals.unshift({
          ...d,
          id,
          ticketId,
          runId: run.id,
          requester: user.id,
          risk,
          riskReason: reason,
          status: 'pending',
          created: Date.now(),
          expires: Date.now() + this.state.config.approvalExpiryMin * 60_000,
          version: 1,
          hash: makeHash(d.type, ticketId, d.payload, 1),
          history: []
        })
        live.output.proposalIds.push(id)
        this.audit(
          'proposal_created',
          id,
          'success',
          `${ACTIONS[d.type].label} proposed (${risk} risk). Awaiting approval.`,
          run.id
        )
      }
    }
    this.audit(
      'investigation_finished',
      ticketId,
      live.status === 'failed' ? 'failure' : 'success',
      `Run ${run.id} ended as ${live.status}${res.error ? ` (${res.error})` : ''}.`,
      run.id
    )
    return live
  }

  async cancelRun(id: string) {
    if (this.mode === 'live') {
      await api.cancelInvestigation(id)
      const r = this.run(id)
      if (r) {
        r.status = 'cancelled'
        r.ended = Date.now()
      }
      this.audit('run_cancelled', id, 'info', `Run ${id} cancelled on backend.`, id)
      return
    }

    const r = this.run(id)
    if (!r || !['queued', 'running'].includes(r.status)) {
      throw new Error('Only queued or running runs can be cancelled.')
    }
    r.status = 'cancelled'
    r.ended = Date.now()
    this.audit('run_cancelled', r.ticketId, 'info', `Run ${id} cancelled before any proposal was created.`, id)
  }

  async retryRun(id: string) {
    const r = this.run(id)
    if (!r || r.status !== 'failed') throw new Error('Only failed runs can be retried.')
    if (this.mode === 'live') {
      await api.retryInvestigation(id)
      return this.investigate(r.ticketId)
    }
    return this.investigate(r.ticketId)
  }

  async labelRun(id: string, label: Run['label'], reason: string) {
    this.need(this.role === 'admin' || this.role === 'lead', 'Only admins and leads can label runs.', 'run_label', id)
    if (this.mode === 'live' && label) {
      await api.labelInvestigation(id, label, reason)
    }
    const r = this.run(id)!
    r.label = label
    r.labelReason = reason
    this.audit('run_labeled', id, 'success', `Label "${label}" recorded. Original run output unchanged.`, id)
  }

  markEvalSample(id: string) {
    this.need(this.role === 'admin', 'Only admins can mark evaluation samples.', 'run_mark_eval', id)
    this.run(id)!.evalSample = true
    this.audit('run_marked_eval', id, 'success', 'Run marked as evaluation sample.', id)
  }

  // ---------- approvals ----------
  sweepExpired() {
    this.pending()
      .filter(p => Date.now() > p.expires)
      .forEach(p => {
        p.status = 'expired'
        this.audit(
          'proposal_expired',
          p.id,
          'info',
          'Approval window elapsed. Proposal cannot execute.',
          p.runId,
          { id: 'system', name: 'System', role: 'admin', team: '', active: true }
        )
      })
  }

  async decide(
    id: string,
    action: 'approve' | 'edit_approve' | 'reject',
    o: { hash: string; payload?: Payload; reason?: string; comment?: string }
  ) {
    const p = this.proposal(id)
    if (!p) throw new Error('Proposal not found.')
    const u = this.user

    // LIVE BACKEND MODE
    if (this.mode === 'live') {
      let updated: BackendProposal
      if (action === 'reject') {
        if (!o.reason) throw new Error('A rejection reason is required.')
        updated = await api.rejectProposal(id, o.hash, o.reason, o.comment)
      } else if (action === 'edit_approve') {
        updated = await api.editApproveProposal(id, o.hash, (o.payload ?? {}) as Record<string, unknown>, o.comment)
      } else {
        updated = await api.approveProposal(id, o.hash, o.comment)
      }

      const mapped = mapBackendProposal(updated)
      Object.assign(p, mapped)

      // Refresh ticket state
      try {
        const bt = await api.getTicket(p.ticketId)
        const t = this.ticket(p.ticketId)
        if (t) Object.assign(t, mapBackendTicket(bt))
      } catch (err) {
        console.warn('Failed to refresh ticket:', err)
      }

      this.audit(
        `proposal_${action}`,
        id,
        'success',
        `Proposal ${action} executed via FastAPI backend (${p.hash}).`,
        p.runId
      )
      return p
    }

    // LOCAL MOCK MODE
    const can = canDecide(u.role, u.id, p)
    this.need(can.ok, can.why ?? 'Not permitted.', 'approval_denied', id)
    this.need(
      p.status === 'pending',
      `Proposal is no longer pending (${p.status}). Duplicate decision blocked.`,
      'duplicate_decision_blocked',
      id
    )
    if (Date.now() > p.expires) {
      p.status = 'expired'
      this.audit('proposal_expired', id, 'denied', 'Attempted to decide an expired proposal.', p.runId)
      throw new Error('Proposal has expired and cannot be approved.')
    }
    this.need(o.hash === p.hash, 'Proposal changed since it was displayed. Review the current version.', 'hash_mismatch_blocked', id)
    if (action === 'reject') {
      if (!o.reason) throw new Error('A rejection reason is required.')
      p.status = 'rejected'
      p.decision = { by: u.id, at: Date.now(), action, reason: o.reason, comment: o.comment }
      this.audit('proposal_rejected', id, 'success', `Rejected: ${o.reason}${o.comment ? ' — ' + o.comment : ''}`, p.runId)
      return p
    }
    if (action === 'edit_approve') {
      const next = { ...p.payload, ...o.payload }
      const allowed = ACTIONS[p.type].editable
      Object.keys(o.payload ?? {}).forEach(k => {
        if (!allowed.includes(k as keyof Payload)) throw new Error(`Field "${k}" is not editable for this action.`)
      })
      const errs = validatePayload(p.type, next, this.state.users)
      if (errs.length) throw new Error(errs.join(' '))
      p.history.push({ version: p.version, payload: { ...p.payload }, by: u.id, ts: Date.now(), note: 'Original payload before edit' })
      p.payload = next
      p.version++
      p.hash = makeHash(p.type, p.ticketId, p.payload, p.version)
      const rk = riskFor(p.type, p.payload)
      p.risk = rk.risk
      p.riskReason = rk.reason
      this.audit('proposal_edited', id, 'success', `Payload edited to v${p.version}. Revalidated; new content hash ${p.hash}.`, p.runId)
    }
    p.status = 'approved'
    p.decision = { by: u.id, at: Date.now(), action, comment: o.comment }
    this.audit('proposal_approved', id, 'success', `Approved v${p.version} (${p.hash}).`, p.runId)
    this.execute(p)
    return p
  }

  /** Mock adapter. Re-checks policy, state, hash and idempotency before touching local synthetic data. */
  private execute(p: Proposal) {
    const key = `${p.id}:${p.hash}`
    if (this.state.executed.includes(key)) {
      this.audit('execution_skipped', p.id, 'info', 'Idempotency key already executed.', p.runId)
      return
    }
    const t = this.ticket(p.ticketId)
    const fail = (why: string) => {
      p.status = 'simulated_failure'
      p.result = why
      this.audit('simulated_execution', p.id, 'failure', `SIMULATED failure: ${why} Approval metadata preserved.`, p.runId)
    }
    if (!t) return fail('Ticket no longer exists.')
    if (makeHash(p.type, p.ticketId, p.payload, p.version) !== p.hash) return fail('Payload hash differs from approved content.')
    const errs = validatePayload(p.type, p.payload, this.state.users)
    if (errs.length) return fail(errs.join(' '))
    const now = Date.now()
    switch (p.type) {
      case 'assign_ticket':
        t.assignee = p.payload.assignee!
        t.team = p.payload.team!
        p.result = `Assigned to ${this.userName(t.assignee)} (${t.team}).`
        break
      case 'add_internal_note':
        t.notes.push({ id: this.nid('note'), by: 'u-system', ts: now, text: p.payload.text!, kind: 'ai_note' })
        p.result = 'Internal note added.'
        break
      case 'draft_customer_reply':
        t.notes.push({ id: this.nid('note'), by: 'u-system', ts: now, text: p.payload.text!, kind: 'reply_draft' })
        p.result = 'Reply draft stored locally. Not sent.'
        break
      case 'request_more_information':
        if (!TRANSITIONS[t.status].includes('waiting_info')) return fail(`Ticket status ${t.status} cannot move to waiting_info.`)
        t.notes.push({ id: this.nid('note'), by: 'u-system', ts: now, text: p.payload.text!, kind: 'info_request' })
        t.status = 'waiting_info'
        p.result = 'Information request stored locally; ticket set to waiting_info. Not sent.'
        break
      case 'change_local_status':
        if (!TRANSITIONS[t.status].includes(p.payload.to as Status)) return fail(`Transition ${t.status} -> ${p.payload.to} is not allowed.`)
        p.result = `Status ${t.status} -> ${p.payload.to}.`
        t.status = p.payload.to!
        break
    }
    t.updated = now
    this.state.executed.push(key)
    p.status = 'simulated_success'
    this.audit('simulated_execution', p.id, 'success', `SIMULATED LOCAL ACTION: ${p.result}`, p.runId)
  }

  // ---------- knowledge ----------
  async toggleSource(id: string) {
    this.need(this.role === 'admin', 'Only admins can change knowledge sources.', 'kb_toggle', id)
    const s = this.state.kb.find(k => k.id === id)!
    const nextStatus = s.status === 'active' ? 'inactive' : 'active'

    if (this.mode === 'live') {
      await api.setKnowledgeStatus(id, nextStatus)
    }

    s.status = nextStatus
    s.updated = Date.now()
    this.audit(
      s.status === 'active' ? 'kb_activated' : 'kb_deactivated',
      id,
      'success',
      'Retrieval eligibility changed. Citation history from earlier runs is unchanged.'
    )
  }

  async reindex(id: string) {
    this.need(this.role === 'admin' || this.role === 'lead', 'Only admins and leads can re-index.', 'kb_reindex', id)
    if (this.mode === 'live') {
      await api.reindexKnowledge(id)
    }
    this.audit('kb_reindexed', id, 'success', 'Chunks re-tokenized (lexical index).')
    this.toast('Re-indexed ' + id, 'ok')
  }

  async addSource(title: string, text: string) {
    this.need(this.role === 'admin', 'Only admins can add sources.', 'kb_add', 'new')
    if (title.trim().length < 3 || text.trim().length < 20) {
      throw new Error('Title (3+) and text (20+ characters) are required.')
    }

    if (this.mode === 'live') {
      const bs = await api.createKnowledgeSource(title.trim(), text.trim())
      this.state.kb.unshift(mapBackendSource(bs))
      this.audit('kb_added', bs.source_key, 'success', 'Manual source added on backend.')
      return
    }

    const id = `kb-manual-${this.nid('s').slice(2)}`
    const chunks = text
      .split(/\n{2,}/)
      .filter(Boolean)
      .slice(0, 12)
      .map((c, i) => ({
        id: `${id}-c${String(i + 1).padStart(2, '0')}`,
        section: `Section ${i + 1}`,
        text: c.trim(),
        keywords: ''
      }))
    this.state.kb.unshift({
      id,
      title: title.trim(),
      type: 'Manual text',
      version: 1,
      owner: this.user.name,
      status: 'active',
      visibility: 'all',
      updated: Date.now(),
      chunks
    })
    this.audit(
      'kb_added',
      id,
      'success',
      `Manual source with ${chunks.length} chunk(s). Content is treated as data, never as instructions.`
    )
  }

  testQuery(q: string) {
    return search(q, this.state.kb, this.role, this.state.config.topK).picked
  }

  // ---------- admin ----------
  async setRole(userId: string, role: Role) {
    this.need(this.role === 'admin', 'Only admins can manage roles.', 'role_change', userId)
    if (this.mode === 'live') {
      await api.setAdminUserRole(userId, role)
    }
    const u = this.state.users.find(x => x.id === userId)!
    this.audit('role_changed', userId, 'success', `${u.role} -> ${role}`)
    u.role = role
  }

  async setConfig(patch: Partial<State['config']>) {
    this.need(this.role === 'admin', 'Only admins can change configuration.', 'config_change', 'config')
    if (this.mode === 'live') {
      const bp: Partial<BackendConfig> = {}
      if (patch.topK !== undefined) bp.top_k = patch.topK
      if (patch.maxRetries !== undefined) bp.max_retries = patch.maxRetries
      if (patch.approvalExpiryMin !== undefined) bp.approval_expiry_minutes = patch.approvalExpiryMin
      if (patch.fault !== undefined) bp.fault = patch.fault
      await api.updateAdminConfig(bp)
    }
    Object.assign(this.state.config, patch)
    this.audit('config_changed', 'config', 'success', JSON.stringify(patch))
  }

  async healthCheck(name: string) {
    this.need(this.role === 'admin', 'Only admins can run health checks.', 'health_check', name)
    if (this.mode === 'live') {
      const ready = await api.checkReady()
      this.state.health[name] = Date.now()
      this.audit('health_check', name, 'success', `FastAPI backend ready check: ${JSON.stringify(ready.checks)}`)
      this.toast(`Backend healthy: ${ready.status}`, 'ok')
      return
    }
    this.state.health[name] = Date.now()
    this.audit('health_check', name, 'success', 'Local mock adapter responded (mock mode).')
    this.toast(`Mock check: ${name} healthy`, 'ok')
  }

  async resetDemo() {
    this.need(this.role === 'admin', 'Only admins can reset the dataset.', 'demo_reset', 'dataset')
    if (this.mode === 'live') {
      await api.resetDemo('RESET')
      await this.syncFromBackend()
      this.audit('demo_reset', 'dataset', 'success', 'FastAPI database reset to fresh demo seed.')
      return
    }
    const keepUser = this.state.userId,
      ver = this.state.datasetVersion + 1
    const fresh = makeSeed()
    Object.assign(this.state, fresh, { userId: keepUser, datasetVersion: ver })
    this.audit('demo_reset', 'dataset', 'success', `Synthetic dataset reset to version ${ver}.`)
  }
}
