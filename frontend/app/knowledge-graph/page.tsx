/**
 * Knowledge Graph Page
 *
 * Main page for the knowledge graph visualization feature.
 * Shows entities, relationships, and timeline in an interactive interface.
 */

'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import api from '@/lib/api';
import { GraphVisualization } from '@/components/knowledge-graph/GraphVisualization';
import { EntityList } from '@/components/knowledge-graph/EntityList';
import { EntityDetail } from '@/components/knowledge-graph/EntityDetail';

interface GraphData {
  nodes: Array<{
    id: string;
    name: string;
    type: string;
    size: number;
    color: string;
  }>;
  edges: Array<{
    source: string;
    target: string;
    label: string;
    weight: number;
  }>;
  entity_count: number;
  relationship_count: number;
}

export default function KnowledgeGraphPage() {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntityType, setSelectedEntityType] = useState<string>('');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [view, setView] = useState<'graph' | 'list' | 'timeline'>('graph');

  useEffect(() => {
    loadGraph();
  }, [selectedEntityType]);

  const loadGraph = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await api.getGraph(selectedEntityType || undefined, 100);
      if (response.data) {
        setGraphData(response.data as GraphData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoading(false);
    }
  };

  const handleNodeClick = (node: any) => {
    setSelectedNodeId(node.id);
  };

  const handleEntitySelect = (entity: any) => {
    setSelectedNodeId(entity.id);
    setView('graph');
  };

  const ENTITY_TYPES = [
    { value: '', label: 'All Types' },
    { value: 'person', label: 'People' },
    { value: 'organization', label: 'Organizations' },
    { value: 'location', label: 'Locations' },
    { value: 'concept', label: 'Concepts' },
    { value: 'event', label: 'Events' },
    { value: 'product', label: 'Products' },
    { value: 'project', label: 'Projects' },
  ];

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <div className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link
                href="/"
                className="p-2 hover:bg-gray-100 rounded-lg transition"
                title="Home"
              >
                <svg className="w-6 h-6 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                </svg>
              </Link>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Knowledge Graph</h1>
                <p className="text-sm text-gray-500">
                  Explore entities, relationships, and timeline events from your documents
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              {/* Entity Type Filter */}
              <select
                value={selectedEntityType}
                onChange={(e) => setSelectedEntityType(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {ENTITY_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>

              {/* View Toggle */}
              <div className="flex rounded-md shadow-sm">
                <button
                  onClick={() => setView('graph')}
                  className={`px-3 py-2 text-sm font-medium border rounded-l-md ${
                    view === 'graph'
                      ? 'bg-blue-50 text-blue-600 border-blue-300'
                      : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  Graph
                </button>
                <button
                  onClick={() => setView('list')}
                  className={`px-3 py-2 text-sm font-medium border-t border-b border-r ${
                    view === 'list'
                      ? 'bg-blue-50 text-blue-600 border-blue-300'
                      : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  List
                </button>
                <button
                  onClick={() => setView('timeline')}
                  className={`px-3 py-2 text-sm font-medium border-t border-b border-r rounded-r-md ${
                    view === 'timeline'
                      ? 'bg-blue-50 text-blue-600 border-blue-300'
                      : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  Timeline
                </button>
              </div>

              {/* Refresh Button */}
              <button
                onClick={loadGraph}
                disabled={loading}
                className="p-2 border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
                title="Refresh"
              >
                <svg
                  className={`w-5 h-5 text-gray-600 ${loading ? 'animate-spin' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Sidebar - Entity List */}
          <div className="lg:col-span-1">
            <EntityList
              entityType={selectedEntityType || undefined}
              onSelectEntity={handleEntitySelect}
              selectedEntityId={selectedNodeId || undefined}
            />
          </div>

          {/* Main Area */}
          <div className="lg:col-span-3 space-y-6">
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <div className="flex">
                  <svg className="w-5 h-5 text-red-400 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                  <div className="text-sm text-red-800">{error}</div>
                </div>
              </div>
            )}

            {view === 'graph' && (
              <>
                {loading ? (
                  <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
                    <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mb-4"></div>
                    <p className="text-gray-500">Loading knowledge graph...</p>
                  </div>
                ) : graphData && graphData.nodes.length > 0 ? (
                  <div className="bg-white rounded-lg border border-gray-200 p-4">
                    <GraphVisualization
                      nodes={graphData.nodes}
                      edges={graphData.edges}
                      width={800}
                      height={500}
                      onNodeClick={handleNodeClick}
                    />
                  </div>
                ) : (
                  <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
                    <svg className="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    <h3 className="text-lg font-medium text-gray-900 mb-2">No entities found</h3>
                    <p className="text-gray-500 mb-4">
                      Extract entities from your documents to build the knowledge graph.
                    </p>
                  </div>
                )}

                {/* Entity Detail Panel */}
                {selectedNodeId && (
                  <EntityDetail
                    entityId={selectedNodeId}
                    onClose={() => setSelectedNodeId(null)}
                  />
                )}
              </>
            )}

            {view === 'list' && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">All Entities</h3>
                <EntityList
                  entityType={selectedEntityType || undefined}
                  onSelectEntity={handleEntitySelect}
                  selectedEntityId={selectedNodeId || undefined}
                />
                {selectedNodeId && (
                  <div className="mt-6">
                    <EntityDetail
                      entityId={selectedNodeId}
                      onClose={() => setSelectedNodeId(null)}
                    />
                  </div>
                )}
              </div>
            )}

            {view === 'timeline' && (
              <TimelineView />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Timeline View Component
 */
function TimelineView() {
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  useEffect(() => {
    // Default to last 30 days
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);

    setEndDate(end.toISOString().split('T')[0]);
    setStartDate(start.toISOString().split('T')[0]);
  }, []);

  useEffect(() => {
    if (startDate && endDate) {
      loadTimeline();
    }
  }, [startDate, endDate]);

  const loadTimeline = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await api.getTimeline(startDate, endDate);
      if (response.data) {
        setEvents((response.data as any).events || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load timeline');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      <div className="p-4 border-b border-gray-200">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Timeline</h3>
        <div className="flex gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">From</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">To</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
      </div>

      <div className="p-4 max-h-[500px] overflow-y-auto">
        {loading ? (
          <div className="text-center text-gray-500 py-8">Loading timeline...</div>
        ) : error ? (
          <div className="text-center text-red-500 py-8">{error}</div>
        ) : events.length === 0 ? (
          <div className="text-center text-gray-500 py-8">No events found in this period</div>
        ) : (
          <div className="space-y-4">
            {events.map((event) => (
              <div key={event.id} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <div className="w-3 h-3 bg-blue-500 rounded-full"></div>
                  <div className="w-0.5 h-full bg-gray-200"></div>
                </div>
                <div className="flex-1 pb-4">
                  <div className="text-sm text-gray-500 mb-1">{event.date}</div>
                  <h4 className="font-medium text-gray-900">{event.title}</h4>
                  {event.description && (
                    <p className="text-sm text-gray-600 mt-1">{event.description}</p>
                  )}
                  {event.type && (
                    <span className="inline-block mt-2 px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs">
                      {event.type}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
