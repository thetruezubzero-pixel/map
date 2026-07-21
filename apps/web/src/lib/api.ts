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

  return res.json() as Promise<T>
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
