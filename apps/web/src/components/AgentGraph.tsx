import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationNodeDatum,
} from 'd3-force'
import type { AgentLevel, AgentSummary } from '@/lib/api'

interface SimNode extends SimulationNodeDatum, AgentSummary {}
interface SimLink {
  source: SimNode
  target: SimNode
}

const LEVEL_COLORS: Record<AgentLevel, string> = {
  amateur: '#5cb8ff',
  actuarial: '#7c5cff',
  coordinator: '#ff5c7c',
}

const WIDTH = 480
const HEIGHT = 360
const MIN_RADIUS = 6
const MAX_RADIUS = 22

/**
 * D3 force-directed graph of agent instances -- node size is
 * current_weight (min-max scaled within the current set), color is
 * level, edges are agent_registry.parent_agent_id (recursive-seniority
 * heirloom lineage -- doubles as the "heirloom family tree" the /heirlooms
 * page needs, since that lineage *is* the parent/child relationship).
 */
export function AgentGraph({ agents, onSelect }: { agents: AgentSummary[]; onSelect?: (id: string) => void }) {
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map())
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)

  const weightRange = useMemo(() => {
    const weights = agents.map((a) => a.current_weight)
    return { min: Math.min(...weights, 1), max: Math.max(...weights, 1) }
  }, [agents])

  const radiusFor = (weight: number) => {
    const { min, max } = weightRange
    if (max === min) return (MIN_RADIUS + MAX_RADIUS) / 2
    return MIN_RADIUS + ((weight - min) / (max - min)) * (MAX_RADIUS - MIN_RADIUS)
  }

  const { simNodes, simLinks } = useMemo(() => {
    const nodeMap = new Map<string, SimNode>(agents.map((a) => [a.id, { ...a }]))
    const links: SimLink[] = agents
      .filter((a) => a.parent_agent_id && nodeMap.has(a.parent_agent_id))
      .map((a) => ({
        source: nodeMap.get(a.parent_agent_id as string) as SimNode,
        target: nodeMap.get(a.id) as SimNode,
      }))
    return { simNodes: Array.from(nodeMap.values()), simLinks: links }
  }, [agents])

  useEffect(() => {
    if (simNodes.length === 0) {
      setPositions(new Map())
      return
    }

    simRef.current?.stop()
    const sim = forceSimulation(simNodes)
      .force('charge', forceManyBody().strength(-160))
      .force('link', forceLink(simLinks).distance(90))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .on('tick', () => {
        // Clamp to the SVG viewport -- forceCenter pulls toward the
        // centroid but doesn't bound individual nodes, so a strongly
        // repelled node can drift past the visible edge (seen live with
        // 7 nodes at default charge strength before this was added).
        const margin = MAX_RADIUS + 15
        for (const n of simNodes) {
          n.x = Math.max(margin, Math.min(WIDTH - margin, n.x ?? WIDTH / 2))
          n.y = Math.max(margin, Math.min(HEIGHT - margin, n.y ?? HEIGHT / 2))
        }
        setPositions(new Map(simNodes.map((n) => [n.id, { x: n.x ?? WIDTH / 2, y: n.y ?? HEIGHT / 2 }])))
      })
    simRef.current = sim

    return () => {
      sim.stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simNodes, simLinks])

  if (agents.length === 0) {
    return <p className="text-sm text-text-muted">No agents registered yet.</p>
  }

  return (
    // width/height stay the D3 simulation's coordinate space (the physics
    // bounds referenced throughout this file); viewBox + a CSS max-width
    // is what actually makes the rendered element shrink to fit a narrow
    // container instead of getting silently clipped -- confirmed live at
    // a 390px viewport: the fixed-pixel version rendered past the edge
    // (SVG right edge at x=504) with no way to see or reach the rest.
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="h-auto w-full max-w-[480px] rounded-md border border-border bg-surface"
      // role="img" would flatten the interactive nodes below out of the
      // accessibility tree entirely -- only appropriate when there's
      // nothing to select.
      role={onSelect ? 'group' : 'img'}
      aria-label={`Agent lineage graph, ${agents.length} agent${agents.length === 1 ? '' : 's'}`}
    >
      {simLinks.map((link, i) => {
        const a = positions.get(link.source.id)
        const b = positions.get(link.target.id)
        if (!a || !b) return null
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--color-border)" strokeWidth={1.5} />
      })}
      {simNodes.map((node) => {
        const pos = positions.get(node.id)
        if (!pos) return null
        return (
          <g
            key={node.id}
            transform={`translate(${pos.x},${pos.y})`}
            className={onSelect ? 'cursor-pointer' : undefined}
            onClick={() => onSelect?.(node.id)}
            {...(onSelect
              ? {
                  role: 'button',
                  tabIndex: 0,
                  'aria-label': `Select agent ${node.name} (${node.role.replace('_', ' ')}, ${node.level})`,
                  onKeyDown: (e: KeyboardEvent) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onSelect(node.id)
                    }
                  },
                }
              : {})}
          >
            <circle
              r={radiusFor(node.current_weight)}
              fill={LEVEL_COLORS[node.level]}
              fillOpacity={node.level === 'amateur' && !node.graduated ? 0.4 : 0.85}
              stroke="white"
              strokeWidth={1.5}
            />
            <text
              x={0}
              y={radiusFor(node.current_weight) + 12}
              fontSize={9}
              textAnchor="middle"
              fill="var(--color-text-muted)"
              className="pointer-events-none select-none"
            >
              {node.role.replace('_', ' ')}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
