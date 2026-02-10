/**
 * Graph Visualization Component for Knowledge Graph
 *
 * Displays entities as nodes and relationships as edges using SVG.
 * Supports zooming, panning, and clicking nodes for details.
 */

'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  size: number;
  color: string;
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  label: string;
  weight: number;
}

interface GraphVisualizationProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width?: number;
  height?: number;
  onNodeClick?: (node: GraphNode) => void;
  onNodeHover?: (node: GraphNode | null) => void;
}

interface SimulationState {
  nodes: (GraphNode & { x: number; y: number; vx: number; vy: number })[];
  edges: GraphEdge[];
}

const ENTITY_COLORS: Record<string, string> = {
  person: '#3B82F6',
  organization: '#10B981',
  location: '#F59E0B',
  concept: '#8B5CF6',
  event: '#EF4444',
  product: '#EC4899',
  project: '#6366F1',
  date: '#6B7280',
  other: '#9CA3AF',
};

const ENTITY_LABELS: Record<string, string> = {
  person: 'Person',
  organization: 'Organization',
  location: 'Location',
  concept: 'Concept',
  event: 'Event',
  product: 'Product',
  project: 'Project',
  date: 'Date',
  other: 'Other',
};

export function GraphVisualization({
  nodes: initialNodes,
  edges,
  width = 800,
  height = 600,
  onNodeClick,
  onNodeHover,
}: GraphVisualizationProps) {
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [draggedNode, setDraggedNode] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [simulatedNodes, setSimulatedNodes] = useState<(GraphNode & { x: number; y: number })[]>([]);

  const svgRef = useRef<SVGSVGElement>(null);
  const dragStartRef = useRef<{ x: number; y: number; nodeX: number; nodeY: number } | null>(null);

  // Initialize node positions
  useEffect(() => {
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.35;

    const positioned = initialNodes.map((node, i) => {
      const angle = (2 * Math.PI * i) / initialNodes.length;
      return {
        ...node,
        x: node.x ?? centerX + radius * Math.cos(angle),
        y: node.y ?? centerY + radius * Math.sin(angle),
        vx: 0,
        vy: 0,
      };
    });

    setSimulatedNodes(positioned);
  }, [initialNodes, width, height]);

  // Simple force simulation
  useEffect(() => {
    if (simulatedNodes.length === 0) return;

    const simulation = setInterval(() => {
      setSimulatedNodes((nodes) => {
        const newNodes = nodes.map((node) => ({
          ...node,
          vx: node.vx * 0.9, // Damping
          vy: node.vy * 0.9,
        }));

        // Repulsion between nodes
        for (let i = 0; i < newNodes.length; i++) {
          for (let j = i + 1; j < newNodes.length; j++) {
            const dx = newNodes[j].x - newNodes[i].x;
            const dy = newNodes[j].y - newNodes[i].y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const force = 500 / (dist * dist);

            newNodes[i].vx -= (dx / dist) * force;
            newNodes[i].vy -= (dy / dist) * force;
            newNodes[j].vx += (dx / dist) * force;
            newNodes[j].vy += (dy / dist) * force;
          }
        }

        // Attraction along edges
        edges.forEach((edge) => {
          const source = newNodes.find((n) => n.id === edge.source);
          const target = newNodes.find((n) => n.id === edge.target);
          if (source && target) {
            const dx = target.x - source.x;
            const dy = target.y - source.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const force = (dist - 100) * 0.05;

            source.vx += (dx / dist) * force;
            source.vy += (dy / dist) * force;
            target.vx -= (dx / dist) * force;
            target.vy -= (dy / dist) * force;
          }
        });

        // Center gravity
        const centerX = width / 2;
        const centerY = height / 2;
        newNodes.forEach((node) => {
          if (draggedNode !== node.id) {
            node.vx += (centerX - node.x) * 0.01;
            node.vy += (centerY - node.y) * 0.01;

            // Apply velocity
            node.x += node.vx;
            node.y += node.vy;

            // Keep within bounds
            node.x = Math.max(50, Math.min(width - 50, node.x));
            node.y = Math.max(50, Math.min(height - 50, node.y));
            node.vx = Math.max(-5, Math.min(5, node.vx));
            node.vy = Math.max(-5, Math.min(5, node.vy));
          }
        });

        return newNodes;
      });
    }, 16);

    return () => clearInterval(simulation);
  }, [edges, width, height, draggedNode]);

  const handleWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const zoomSensitivity = 0.001;
    const newK = Math.max(0.1, Math.min(4, transform.k - e.deltaY * zoomSensitivity));

    // Zoom towards cursor position
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;

    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const newX = mouseX - (mouseX - transform.x) * (newK / transform.k);
    const newY = mouseY - (mouseY - transform.y) * (newK / transform.k);

    setTransform({ k: newK, x: newX, y: newY });
  }, [transform]);

  const handleMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (e.target === svgRef.current) {
      setIsDragging(true);
      dragStartRef.current({ x: e.clientX - transform.x, y: e.clientY - transform.y, nodeX: 0, nodeY: 0 });
    }
  }, [transform]);

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (isDragging && dragStartRef.current && !draggedNode) {
      const x = e.clientX - dragStartRef.current.x;
      const y = e.clientY - dragStartRef.current.y;
      setTransform((prev) => ({ ...prev, x, y }));
    }
  }, [isDragging, draggedNode]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    setDraggedNode(null);
    dragStartRef.current = null;
  }, []);

  const handleNodeMouseDown = useCallback((e: React.MouseEvent, node: GraphNode & { x: number; y: number }) => {
    e.stopPropagation();
    setDraggedNode(node.id);
    dragStartRef.current({
      x: e.clientX - node.x * transform.k - transform.x,
      y: e.clientY - node.y * transform.k - transform.y,
      nodeX: node.x,
      nodeY: node.y,
    });
  }, [transform]);

  const handleNodeMouseMove = useCallback((e: React.MouseEvent, node: GraphNode & { x: number; y: number }) => {
    if (draggedNode === node.id && dragStartRef.current) {
      const newNodeX = (e.clientX - dragStartRef.current.x - transform.x) / transform.k;
      const newNodeY = (e.clientY - dragStartRef.current.y - transform.y) / transform.k;

      setSimulatedNodes((nodes) =>
        nodes.map((n) => (n.id === node.id ? { ...n, x: newNodeX, y: newNodeY, vx: 0, vy: 0 } : n))
      );
    }
  }, [draggedNode, transform]);

  const getNodeRadius = (size: number) => Math.max(15, Math.min(40, 10 + size * 3));

  return (
    <div className="relative w-full h-full bg-gray-50 rounded-lg overflow-hidden border border-gray-200">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        className="cursor-grab active:cursor-grabbing"
      >
        <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>
          {/* Edges */}
          {edges.map((edge, i) => {
            const source = simulatedNodes.find((n) => n.id === edge.source);
            const target = simulatedNodes.find((n) => n.id === edge.target);
            if (!source || !target) return null;

            return (
              <g key={`edge-${i}`}>
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke="#CBD5E1"
                  strokeWidth={Math.min(3, 1 + edge.weight * 0.5)}
                  opacity={0.6}
                />
                {/* Edge label */}
                <text
                  x={(source.x + target.x) / 2}
                  y={(source.y + target.y) / 2}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#64748B"
                  className="pointer-events-none"
                >
                  {edge.label}
                </text>
              </g>
            );
          })}

          {/* Nodes */}
          {simulatedNodes.map((node) => (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              onMouseDown={(e) => handleNodeMouseDown(e, node)}
              onMouseMove={(e) => handleNodeMouseMove(e, node)}
              onClick={() => onNodeClick?.(node)}
              onMouseEnter={() => {
                setHoveredNode(node);
                onNodeHover?.(node);
              }}
              onMouseLeave={() => {
                setHoveredNode(null);
                onNodeHover?.(null);
              }}
              className="cursor-pointer transition-opacity"
              style={{ opacity: hoveredNode && hoveredNode.id !== node.id ? 0.3 : 1 }}
            >
              {/* Node circle */}
              <circle
                r={getNodeRadius(node.size)}
                fill={ENTITY_COLORS[node.type] || ENTITY_COLORS.other}
                stroke={hoveredNode?.id === node.id ? '#1F2937' : '#FFFFFF'}
                strokeWidth={hoveredNode?.id === node.id ? 3 : 2}
              />

              {/* Node label */}
              <text
                y={getNodeRadius(node.size) + 14}
                textAnchor="middle"
                fontSize="11"
                fontWeight="500"
                fill="#374151"
                className="pointer-events-none"
              >
                {node.name.length > 15 ? node.name.substring(0, 15) + '...' : node.name}
              </text>
            </g>
          ))}
        </g>
      </svg>

      {/* Controls */}
      <div className="absolute bottom-4 right-4 flex gap-2">
        <button
          onClick={() => setTransform({ k: transform.k * 1.2, x: transform.x, y: transform.y })}
          className="p-2 bg-white rounded shadow hover:bg-gray-50 border border-gray-200"
          title="Zoom in"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
        </button>
        <button
          onClick={() => setTransform({ k: transform.k / 1.2, x: transform.x, y: transform.y })}
          className="p-2 bg-white rounded shadow hover:bg-gray-50 border border-gray-200"
          title="Zoom out"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
          </svg>
        </button>
        <button
          onClick={() => setTransform({ k: 1, x: 0, y: 0 })}
          className="p-2 bg-white rounded shadow hover:bg-gray-50 border border-gray-200"
          title="Reset view"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      {/* Legend */}
      <div className="absolute top-4 left-4 bg-white p-3 rounded shadow border border-gray-200">
        <h3 className="text-xs font-semibold text-gray-700 mb-2">Entity Types</h3>
        <div className="space-y-1">
          {Object.entries(ENTITY_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: color }}
              />
              <span className="text-xs text-gray-600">{ENTITY_LABELS[type] || type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Stats */}
      <div className="absolute top-4 right-4 bg-white p-3 rounded shadow border border-gray-200">
        <div className="text-xs text-gray-600">
          <div>Nodes: {simulatedNodes.length}</div>
          <div>Edges: {edges.length}</div>
        </div>
      </div>
    </div>
  );
}

export default GraphVisualization;
