import { useEffect, useMemo, useRef, useState } from 'react'
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationNodeDatum,
} from 'd3-force'
import { getEntityGraph, type GraphEdge, type GraphNode } from '@/lib/api'
import { useMapStore } from '@/store/useMapStore'

interface SimNode extends SimulationNodeDatum, GraphNode {}
interface SimLink {
  source: SimNode
  target: SimNode
  relation_type: string
}

const NODE_COLORS: Record<string, string> = {
  business: '#7c5cff',
  government_filing: '#34d3a3',
  location: '#f5a623',
  poi: '#f5a623',
  news_mention: '#ff5c7c',
}

const WIDTH = 320
const HEIGHT = 260

/**
 * D3 force-directed graph of business entity relationships (parent/
 * subsidiary, resolved same_as duplicates). Business entities only.
 */
export function EntityGraphView({ entityId }: { entityId: string }) {
  const setSelectedEntityId = useMapStore((s) => s.setSelectedEntityId)
  const [rawNodes, setRawNodes] = useState<GraphNode[]>([])
  const [rawEdges, setRawEdges] = useState<GraphEdge[]>([])
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map())
  const [error, setError] = useState<string | null>(null)
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    getEntityGraph(entityId, 2)
      .then((res) => {
        if (cancelled) return
        setRawNodes(res.nodes)
        setRawEdges(res.edges)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'failed to load graph')
      })
    return () => {
      cancelled = true
    }
  }, [entityId])

  const { simNodes, simLinks } = useMemo(() => {
    const nodeMap = new Map<string, SimNode>(rawNodes.map((n) => [n.id, { ...n }]))
    const links: SimLink[] = rawEdges
      .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map((e) => ({
        source: nodeMap.get(e.source) as SimNode,
        target: nodeMap.get(e.target) as SimNode,
        relation_type: e.relation_type,
      }))
    return { simNodes: Array.from(nodeMap.values()), simLinks: links }
  }, [rawNodes, rawEdges])

  useEffect(() => {
    if (simNodes.length === 0) {
      setPositions(new Map())
      return
    }

    simRef.current?.stop()
    const sim = forceSimulation(simNodes)
      .force('charge', forceManyBody().strength(-120))
      .force('link', forceLink(simLinks).distance(70))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .on('tick', () => {
        setPositions(
          new Map(simNodes.map((n) => [n.id, { x: n.x ?? WIDTH / 2, y: n.y ?? HEIGHT / 2 }])),
        )
      })
    simRef.current = sim

    return () => {
      sim.stop()
    }
    // simNodes/simLinks are rebuilt whole-array each fetch, so this effect
    // intentionally re-runs whenever the graph data changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simNodes, simLinks])

  if (error) {
    return <p className="text-xs text-red-400">{error}</p>
  }

  if (rawNodes.length === 0) {
    return <p className="text-xs text-text-muted">No relationships found for this entity yet.</p>
  }

  return (
    <svg width={WIDTH} height={HEIGHT} className="rounded-md border border-border bg-surface">
      {simLinks.map((link, i) => {
        const a = positions.get(link.source.id)
        const b = positions.get(link.target.id)
        if (!a || !b) return null
        return (
          <line
            key={i}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="var(--color-border)"
            strokeWidth={link.relation_type === 'same_as' ? 1.5 : 1}
            strokeDasharray={link.relation_type === 'same_as' ? '4 2' : undefined}
          />
        )
      })}
      {simNodes.map((node) => {
        const pos = positions.get(node.id)
        if (!pos) return null
        return (
          <g
            key={node.id}
            transform={`translate(${pos.x},${pos.y})`}
            className="cursor-pointer"
            onClick={() => setSelectedEntityId(node.id)}
          >
            <circle
              r={node.id === entityId ? 9 : 6}
              fill={NODE_COLORS[node.entity_type] ?? '#7c5cff'}
              stroke="white"
              strokeWidth={1.5}
            />
            <text
              x={10}
              y={4}
              fontSize={10}
              fill="var(--color-text)"
              className="pointer-events-none select-none"
            >
              {node.name.length > 24 ? `${node.name.slice(0, 24)}…` : node.name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
