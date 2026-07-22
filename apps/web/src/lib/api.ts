const GATEWAY_URL = import.meta.env.VITE_GATEWAY_URL ?? '/api'
const PY_API_URL = import.meta.env.VITE_PY_API_URL ?? '/py-api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function requestFrom<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new ApiError(body.error ?? body.detail ?? res.statusText, res.status)
  }

  // DELETE /subscriptions/:id (and any other 200/204-with-empty-body
  // response) has no JSON to parse -- res.json() on an empty body throws
  // "Unexpected end of JSON input" rather than returning undefined.
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

function request<T>(path: string, init?: RequestInit): Promise<T> {
  return requestFrom<T>(GATEWAY_URL, path, init)
}

// Requests to the Python orchestration/analytics service (research jobs,
// entity graph, ES-backed analytics) rather than the Rust gateway.
function pyRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return requestFrom<T>(PY_API_URL, path, init)
}

export interface GeocodeHit {
  place_id: number
  display_name: string
  lat: string
  lon: string
  type: string
}

export function geocode(q: string, limit = 5): Promise<GeocodeHit[]> {
  const params = new URLSearchParams({ q, limit: String(limit) })
  return request<GeocodeHit[]>(`/geocode?${params.toString()}`)
}

export const ENTITY_TYPES = [
  'business',
  'government_filing',
  'location',
  'poi',
  'news_mention',
] as const
export type EntityType = (typeof ENTITY_TYPES)[number]

export interface SearchResult {
  id: string
  name: string
  entity_type: EntityType
  source: string
  license: string | null
  lon: number | null
  lat: number | null
  distance_m: number | null
  retrieved_at: string
}

export interface SearchParams {
  q?: string
  lat?: number
  lon?: number
  radius_m?: number
  source?: string
  entity_type?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export function search(params: SearchParams): Promise<{ results: SearchResult[]; count: number }> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value))
    }
  }
  return request(`/search?${query.toString()}`)
}

export interface EntityDetail extends SearchResult {
  metadata: Record<string, unknown>
}

export function getEntity(id: string): Promise<EntityDetail> {
  return request<EntityDetail>(`/entities/${id}`)
}

export function createResearchJob(query: string, token?: string): Promise<{ job_id: string; status: string }> {
  return request('/research', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: JSON.stringify({ query }),
  })
}

// --- Entity graph (business parent/subsidiary + resolved-duplicate edges) ---

export interface GraphNode {
  id: string
  name: string
  entity_type: EntityType
  source: string
}

export interface GraphEdge {
  source: string
  target: string
  relation_type: string
  edge_source: string
}

export function getEntityGraph(entityId: string, depth = 1): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  return pyRequest(`/graph/${entityId}?depth=${depth}`)
}

export interface ResolutionCandidate {
  id: string
  entity_a_id: string
  entity_a_name: string
  entity_b_id: string
  entity_b_name: string
  confidence: number
  match_basis: Record<string, number>
  status: string
}

export function getReviewQueue(): Promise<ResolutionCandidate[]> {
  return pyRequest('/graph/review/queue')
}

export function reviewCandidate(
  candidateId: string,
  decision: 'confirm' | 'reject',
  reviewedBy?: string,
): Promise<{ id: string; status: string }> {
  return pyRequest(`/graph/review/${candidateId}`, {
    method: 'POST',
    body: JSON.stringify({ decision, reviewed_by: reviewedBy }),
  })
}

// --- Analytics (Elasticsearch-backed geospatial aggregations) ---

export interface HeatmapBucket {
  geohash: string
  count: number
  centroid: { lat: number; lon: number }
}

export function getHeatmap(entityType?: EntityType, precision = 5): Promise<{ buckets: HeatmapBucket[] }> {
  const params = new URLSearchParams({ precision: String(precision) })
  if (entityType) params.set('entity_type', entityType)
  return pyRequest(`/analytics/heatmap?${params.toString()}`)
}

export function getNearby(
  lat: number,
  lon: number,
  radiusKm: number,
  entityType?: EntityType,
): Promise<{ results: SearchResult[]; count: number }> {
  const params = new URLSearchParams({ lat: String(lat), lon: String(lon), radius_km: String(radiusKm) })
  if (entityType) params.set('entity_type', entityType)
  return pyRequest(`/analytics/nearby?${params.toString()}`)
}

// --- Phase 4: alert subscriptions + streaming health ---
// Unlike /research, these are hard-JWT-required by the gateway (401
// without a token) -- see apps/gateway/src/middleware/auth.rs
// require_user_id. There is no login/signup flow anywhere in this app
// yet (no users table, no /login endpoint) -- the token has to come from
// somewhere else (an ops-issued JWT signed with the same JWT_SECRET the
// gateway uses). AlertPanel below just asks the user to paste one in;
// that is a real, documented gap, not a stand-in for a real auth flow.

export const SUBSCRIPTION_TYPES = ['entity', 'keyword', 'geofence', 'composite'] as const
export type SubscriptionType = (typeof SUBSCRIPTION_TYPES)[number]

export const ALERT_SEVERITIES = ['INFO', 'WARNING', 'CRITICAL'] as const
export type AlertSeverity = (typeof ALERT_SEVERITIES)[number]

export interface Subscription {
  id: string
  user_id: string
  subscription_type: SubscriptionType
  criteria: Record<string, unknown>
  min_severity: AlertSeverity
  channels: string[]
  webhook_url: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface CreateSubscriptionInput {
  subscription_type: SubscriptionType
  criteria: Record<string, unknown>
  min_severity?: AlertSeverity
  channels?: string[]
  webhook_url?: string | null
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` }
}

export function listSubscriptions(token: string): Promise<Subscription[]> {
  return request<Subscription[]>('/subscriptions', { headers: authHeaders(token) })
}

export function createSubscription(token: string, input: CreateSubscriptionInput): Promise<Subscription> {
  return request<Subscription>('/subscriptions', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(input),
  })
}

export function updateSubscription(
  token: string,
  id: string,
  patch: Partial<Pick<Subscription, 'criteria' | 'min_severity' | 'channels' | 'webhook_url' | 'is_active'>>,
): Promise<Subscription> {
  return request<Subscription>(`/subscriptions/${id}`, {
    method: 'PATCH',
    headers: authHeaders(token),
    body: JSON.stringify(patch),
  })
}

export function deleteSubscription(token: string, id: string): Promise<void> {
  return request<void>(`/subscriptions/${id}`, { method: 'DELETE', headers: authHeaders(token) })
}

export interface AlertMessage {
  id: string
  subscription_id: string
  user_id: string
  severity: AlertSeverity
  title: string
  description: string
  source_topic: string
  source_event_id: string | null
  entity_id: string | null
  lat: number | null
  lon: number | null
  channels: string[]
  created_at: string
}

/** Builds the ws(s):// URL for GET /ws/alerts from the same GATEWAY_URL
 * used for HTTP requests -- handles both a relative dev-proxy path
 * (/api) and an absolute gateway URL, and always matches the page's
 * own protocol (ws under http, wss under https). */
export function alertsWebSocketUrl(token: string): string {
  const base = new URL(GATEWAY_URL, window.location.origin)
  const wsProtocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
  const path = `${base.pathname.replace(/\/$/, '')}/ws/alerts`
  return `${wsProtocol}//${base.host}${path}?token=${encodeURIComponent(token)}`
}

export interface StreamingHealth {
  status: string
  kafka: {
    reachable: boolean
    error?: string
    topics?: { topic: string; found: boolean; partition_count?: number; message_count?: number }[]
  }
  schema_registry: { reachable: boolean }
  ksqldb: { reachable: boolean }
  flink: { reachable: boolean; jobs?: { jobs: { jid: string; state: string; name: string }[] } }
}

export function getStreamingHealth(): Promise<StreamingHealth> {
  return request<StreamingHealth>('/health/streaming')
}

// --- Export helpers (client-side, no backend round trip) ---

export function downloadJSON(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  triggerDownload(filename, blob)
}

export function downloadCSV(filename: string, rows: SearchResult[]): void {
  const headers = ['id', 'name', 'entity_type', 'source', 'license', 'lat', 'lon', 'retrieved_at']
  const escape = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const lines = [
    headers.join(','),
    ...rows.map((r) => headers.map((h) => escape((r as unknown as Record<string, unknown>)[h])).join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  triggerDownload(filename, blob)
}

function triggerDownload(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// --- Phase 5: weighted agent swarm (app/agent_swarm/, apps/api/python/app/routers/agent_swarm.py) ---

export const AGENT_ROLES = ['query_analyzer', 'data_retriever', 'result_synthesizer'] as const
export type AgentRole = (typeof AGENT_ROLES)[number]

export const AGENT_LEVELS = ['amateur', 'actuarial', 'coordinator'] as const
export type AgentLevel = (typeof AGENT_LEVELS)[number]

export interface AgentSummary {
  id: string
  name: string
  role: AgentRole
  level: AgentLevel
  model: string
  current_weight: number
  consecutive_successes: number
  total_tasks: number
  total_successes: number
  accuracy: number | null
  graduated: boolean
  parent_agent_id: string | null
  mentor_agent_id: string | null
  user_id: string | null
}

export interface WeightHistoryEntry {
  weight: number
  delta: number
  reason: string
  created_at: string
}

export interface AgentTaskEntry {
  id: string
  role: AgentRole
  consensus_output: Record<string, unknown>
  was_winner: boolean
  reward_applied: boolean
  created_at: string
}

export interface AgentDetail extends AgentSummary {
  recent_tasks: AgentTaskEntry[]
  weight_trajectory: WeightHistoryEntry[]
}

export function listAgents(userId?: string): Promise<AgentSummary[]> {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
  return pyRequest<AgentSummary[]>(`/agents${params}`)
}

export function getAgent(agentId: string): Promise<AgentDetail> {
  return pyRequest<AgentDetail>(`/agents/${agentId}`)
}

export interface SwarmVote {
  agent_id: string
  agent_level: AgentLevel
  weight: number
  confidence: number
  output_key: string
  reasoning: string
}

export interface SwarmTask {
  id: string
  job_id: string | null
  role: AgentRole
  agent_count: number
  votes: SwarmVote[]
  winning_agent_id: string | null
  reward_applied: boolean
  created_at: string
}

export function getSwarmActivity(limit = 50): Promise<{ tasks: SwarmTask[] }> {
  return pyRequest(`/swarm?limit=${limit}`)
}

export interface TrainingEntry {
  id: string
  role: AgentRole
  model: string
  total_tasks: number
  total_successes: number
  accuracy: number | null
  consecutive_successes: number
  consecutive_needed: number
  accuracy_needed: number
  graduated: boolean
  mentor_agent_id: string | null
}

export function getTrainingProgress(userId?: string): Promise<{ amateurs: TrainingEntry[] }> {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
  return pyRequest(`/training${params}`)
}

export interface Heirloom {
  id: string
  agent_id: string
  agent_name: string
  role: AgentRole
  level: AgentLevel
  device_id: string
  backend: string
  content_hash: string
  verified: boolean
  created_at: string
}

export function listHeirlooms(userId?: string): Promise<{ heirlooms: Heirloom[] }> {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
  return pyRequest(`/heirlooms${params}`)
}

export function exportHeirloom(agentId: string, userId: string, deviceId: string): Promise<Heirloom> {
  return pyRequest<Heirloom>(`/heirlooms/${agentId}/export`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, device_id: deviceId }),
  })
}
