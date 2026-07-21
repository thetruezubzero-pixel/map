const GATEWAY_URL = import.meta.env.VITE_GATEWAY_URL ?? '/api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new ApiError(body.error ?? res.statusText, res.status)
  }

  return res.json() as Promise<T>
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
