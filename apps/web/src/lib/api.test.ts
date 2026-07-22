import { beforeEach, describe, expect, it, vi } from 'vitest'
import { downloadCSV, downloadJSON, type SearchResult } from './api'

describe('export helpers', () => {
  let createdBlobs: Blob[]
  let clicked: HTMLAnchorElement[]

  beforeEach(() => {
    createdBlobs = []
    clicked = []
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn((blob: Blob) => {
        createdBlobs.push(blob)
        return 'blob:mock'
      }),
      revokeObjectURL: vi.fn(),
    })
    vi.restoreAllMocks()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      // jsdom doesn't implement anchor-click navigation -- just record the call.
      clicked.push(this)
    })
  })

  it('downloadJSON creates a JSON blob and triggers a click', async () => {
    downloadJSON('report.json', { foo: 'bar' })
    expect(createdBlobs).toHaveLength(1)
    expect(createdBlobs[0].type).toBe('application/json')
    const text = await createdBlobs[0].text()
    expect(JSON.parse(text)).toEqual({ foo: 'bar' })
    expect(clicked).toHaveLength(1)
    expect(clicked[0].download).toBe('report.json')
  })

  it('downloadCSV escapes embedded quotes and commas', async () => {
    const rows: SearchResult[] = [
      {
        id: '1',
        name: 'Acme, "The" Holdings',
        entity_type: 'business',
        source: 'test',
        license: null,
        lon: -73.9,
        lat: 40.7,
        distance_m: null,
        retrieved_at: '2026-01-01T00:00:00Z',
      },
    ]
    downloadCSV('results.csv', rows)
    const text = await createdBlobs[0].text()
    const lines = text.split('\n')
    expect(lines[0]).toBe('id,name,entity_type,source,license,lat,lon,retrieved_at')
    expect(lines[1]).toContain('"Acme, ""The"" Holdings"')
  })
})
