import type {
  BackendAuditEvent,
  BackendConfig,
  BackendNote,
  BackendProposal,
  BackendRun,
  BackendRunEvent,
  BackendSource,
  BackendTicket,
  BackendUser
} from './types'

const TOKEN_KEY = 'fieldops_access_token'
const USER_KEY = 'fieldops_user_id'

export class ApiError extends Error {
  code: string
  status: number
  constructor(message: string, code = 'ERROR', status = 500) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

export class ApiClient {
  baseUrl: string
  token: string | null = null
  userId: string | null = null

  constructor(baseUrl = '/api/v1') {
    this.baseUrl = baseUrl.replace(/\/$/, '')
    this.token = localStorage.getItem(TOKEN_KEY)
    this.userId = localStorage.getItem(USER_KEY)
  }

  setToken(token: string | null, userId?: string | null) {
    this.token = token
    if (token) {
      localStorage.setItem(TOKEN_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_KEY)
    }
    if (userId !== undefined) {
      this.userId = userId
      if (userId) {
        localStorage.setItem(USER_KEY, userId)
      } else {
        localStorage.removeItem(USER_KEY)
      }
    }
  }

  private genCorrelationId(): string {
    return 'cid-' + Math.random().toString(36).substring(2, 12) + Date.now().toString(36)
  }

  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Correlation-ID': this.genCorrelationId(),
      ...((options.headers as Record<string, string>) || {})
    }

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`
    }

    let res: Response
    try {
      res = await fetch(url, { credentials: 'omit', ...options, headers })
    } catch (err) {
      throw new ApiError(`Network error connecting to backend: ${(err as Error).message}`, 'NETWORK_ERROR', 0)
    }

    if (!res.ok) {
      let code = `HTTP_${res.status}`
      let message = `Request failed with status ${res.status}`
      try {
        const body = await res.json()
        if (body.code) code = body.code
        if (body.message) message = body.message
        else if (body.detail) {
          message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
        }
      } catch {
        // use default message
      }
      throw new ApiError(message, code, res.status)
    }

    if (res.status === 204) {
      return {} as T
    }

    return (await res.json()) as T
  }

  // Health
  async checkLive(): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseUrl}/health/live`, { method: 'GET' })
      return res.ok
    } catch {
      return false
    }
  }

  async checkReady(): Promise<{ status: string; checks: Record<string, string>; model_mode: string; connector_mode: string }> {
    return this.request('/health/ready')
  }

  // Auth
  async getDemoUsers(): Promise<{ simulated_auth: boolean; warning: string; users: BackendUser[] }> {
    return this.request('/auth/demo-users')
  }

  async demoLogin(userId: string): Promise<{ access_token: string; token_type: string; expires_in: number; simulated_auth: boolean }> {
    const res = await this.request<{ access_token: string; token_type: string; expires_in: number; simulated_auth: boolean }>(
      '/auth/demo-login',
      {
        method: 'POST',
        body: JSON.stringify({ user_id: userId })
      }
    )
    this.setToken(res.access_token, userId)
    return res
  }

  async me(): Promise<{ id: string; display_name: string; email?: string; role: string; team?: string; permissions: string[]; workspace: { id: string; name: string; mode: string } }> {
    return this.request('/me')
  }

  logout() {
    this.setToken(null, null)
  }

  // Overview
  async getOverview(): Promise<Record<string, unknown>> {
    return this.request('/overview')
  }

  // Tickets
  async listTickets(params: Record<string, string | number | undefined> = {}): Promise<{ items: BackendTicket[]; total: number; page: number; page_size: number }> {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') q.append(k, String(v))
    })
    const queryStr = q.toString() ? `?${q.toString()}` : ''
    return this.request(`/tickets${queryStr}`)
  }

  async getTicket(ticketId: string): Promise<BackendTicket> {
    return this.request(`/tickets/${encodeURIComponent(ticketId)}`)
  }

  async createTicket(data: {
    title: string
    description: string
    category: string
    priority: string
    asset_tag?: string
    customer_alias?: string
  }): Promise<BackendTicket> {
    return this.request('/tickets', {
      method: 'POST',
      body: JSON.stringify(data)
    })
  }

  async addNote(ticketId: string, text: string): Promise<{ items: BackendNote[] }> {
    return this.request(`/tickets/${encodeURIComponent(ticketId)}/notes`, {
      method: 'POST',
      body: JSON.stringify({ text })
    })
  }

  async assign(ticketId: string, assigneeId: string | null): Promise<BackendTicket> {
    return this.request(`/tickets/${encodeURIComponent(ticketId)}/assignment`, {
      method: 'PUT',
      body: JSON.stringify({ assignee_id: assigneeId })
    })
  }

  async getTicketEvents(ticketId: string): Promise<{ items: BackendNote[] }> {
    return this.request(`/tickets/${encodeURIComponent(ticketId)}/events`)
  }

  // Investigations
  async startInvestigation(
    ticketId: string,
    options: { mode?: string; include_related_cases?: boolean; retrieval_profile?: string } = {}
  ): Promise<BackendRun> {
    return this.request(`/tickets/${encodeURIComponent(ticketId)}/investigations`, {
      method: 'POST',
      body: JSON.stringify({
        mode: options.mode || 'fixture',
        include_related_cases: options.include_related_cases ?? true,
        retrieval_profile: options.retrieval_profile || 'lexical_v1'
      })
    })
  }

  async listTicketInvestigations(ticketId: string): Promise<{ items: BackendRun[] }> {
    return this.request(`/tickets/${encodeURIComponent(ticketId)}/investigations`)
  }

  async listInvestigations(params: Record<string, string | undefined> = {}): Promise<{ items: BackendRun[] }> {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') q.append(k, v)
    })
    const queryStr = q.toString() ? `?${q.toString()}` : ''
    return this.request(`/investigations${queryStr}`)
  }

  async getInvestigation(runId: string): Promise<BackendRun> {
    return this.request(`/investigations/${encodeURIComponent(runId)}`)
  }

  async getInvestigationEvents(runId: string): Promise<{ run_status: string; items: BackendRunEvent[] }> {
    return this.request(`/investigations/${encodeURIComponent(runId)}/events`)
  }

  async cancelInvestigation(runId: string): Promise<BackendRun> {
    return this.request(`/investigations/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })
  }

  async retryInvestigation(runId: string): Promise<BackendRun> {
    return this.request(`/investigations/${encodeURIComponent(runId)}/retry`, { method: 'POST' })
  }

  async labelInvestigation(runId: string, label: string, reason = ''): Promise<BackendRun> {
    return this.request(`/investigations/${encodeURIComponent(runId)}/label`, {
      method: 'POST',
      body: JSON.stringify({ label, reason })
    })
  }

  // Proposals
  async listProposals(params: Record<string, string | undefined> = {}): Promise<{ items: BackendProposal[] }> {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') q.append(k, v)
    })
    const queryStr = q.toString() ? `?${q.toString()}` : ''
    return this.request(`/action-proposals${queryStr}`)
  }

  async getProposal(pid: string): Promise<BackendProposal> {
    return this.request(`/action-proposals/${encodeURIComponent(pid)}`)
  }

  async approveProposal(pid: string, payloadHash: string, comment?: string): Promise<BackendProposal> {
    return this.request(`/action-proposals/${encodeURIComponent(pid)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ payload_hash: payloadHash, comment })
    })
  }

  async editApproveProposal(
    pid: string,
    payloadHash: string,
    editedPayload: Record<string, unknown>,
    comment?: string
  ): Promise<BackendProposal> {
    return this.request(`/action-proposals/${encodeURIComponent(pid)}/edit-approve`, {
      method: 'POST',
      body: JSON.stringify({ payload_hash: payloadHash, edited_payload: editedPayload, comment })
    })
  }

  async rejectProposal(pid: string, payloadHash: string, reasonCode: string, comment?: string): Promise<BackendProposal> {
    return this.request(`/action-proposals/${encodeURIComponent(pid)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ payload_hash: payloadHash, reason_code: reasonCode, comment })
    })
  }

  async retryProposalExecution(pid: string): Promise<BackendProposal> {
    return this.request(`/action-proposals/${encodeURIComponent(pid)}/retry-execution`, { method: 'POST' })
  }

  // Knowledge
  async listKnowledgeSources(): Promise<{ items: BackendSource[] }> {
    return this.request('/knowledge/sources')
  }

  async getKnowledgeSource(ident: string): Promise<BackendSource> {
    return this.request(`/knowledge/sources/${encodeURIComponent(ident)}`)
  }

  async searchKnowledge(query: string, topK?: number): Promise<{ items: any[] }> {
    return this.request('/knowledge/search', {
      method: 'POST',
      body: JSON.stringify({ query, top_k: topK })
    })
  }

  async createKnowledgeSource(title: string, text: string): Promise<BackendSource> {
    return this.request('/knowledge/sources', {
      method: 'POST',
      body: JSON.stringify({ title, text })
    })
  }

  async newKnowledgeVersion(ident: string, text: string): Promise<BackendSource> {
    return this.request(`/knowledge/sources/${encodeURIComponent(ident)}/versions`, {
      method: 'POST',
      body: JSON.stringify({ text })
    })
  }

  async setKnowledgeStatus(ident: string, status: 'active' | 'inactive'): Promise<BackendSource> {
    return this.request(`/knowledge/sources/${encodeURIComponent(ident)}/status`, {
      method: 'PUT',
      body: JSON.stringify({ status })
    })
  }

  async reindexKnowledge(ident: string): Promise<BackendSource> {
    return this.request(`/knowledge/sources/${encodeURIComponent(ident)}/reindex`, { method: 'POST' })
  }

  // Evaluations
  async listEvaluationDatasets(): Promise<{ items: any[] }> {
    return this.request('/evaluations/datasets')
  }

  async startEvaluationRun(datasetId?: string): Promise<any> {
    return this.request('/evaluations/runs', {
      method: 'POST',
      body: JSON.stringify({ dataset_id: datasetId })
    })
  }

  async listEvaluationRuns(): Promise<{ items: any[] }> {
    return this.request('/evaluations/runs')
  }

  async getEvaluationRun(rid: string): Promise<any> {
    return this.request(`/evaluations/runs/${encodeURIComponent(rid)}`)
  }

  // Audit
  async listAuditEvents(params: Record<string, string | number | undefined> = {}): Promise<{ items: BackendAuditEvent[]; page: number; page_size: number }> {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') q.append(k, String(v))
    })
    const queryStr = q.toString() ? `?${q.toString()}` : ''
    return this.request(`/audit-events${queryStr}`)
  }

  // Admin
  async getAdminConfig(): Promise<BackendConfig> {
    return this.request('/admin/config')
  }

  async updateAdminConfig(patch: Partial<BackendConfig>): Promise<BackendConfig> {
    return this.request('/admin/config', {
      method: 'PUT',
      body: JSON.stringify(patch)
    })
  }

  async listAdminUsers(): Promise<{ items: BackendUser[] }> {
    return this.request('/admin/users')
  }

  async setAdminUserRole(userId: string, role: string): Promise<{ items: BackendUser[] }> {
    return this.request(`/admin/users/${encodeURIComponent(userId)}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role })
    })
  }

  async resetDemo(confirm = 'RESET'): Promise<any> {
    return this.request('/admin/demo-reset', {
      method: 'POST',
      body: JSON.stringify({ confirm })
    })
  }
}

export const api = new ApiClient()
