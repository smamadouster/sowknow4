/**
 * Entity List Component
 *
 * Displays a list of entities with filtering and search capabilities.
 */

'use client';

import React, { useState, useEffect } from 'react';
import api from '@/lib/api';

export interface Entity {
  id: string;
  name: string;
  type: string;
  canonical_id?: string;
  document_count: number;
  relationship_count: number;
  first_seen?: string;
  last_seen?: string;
}

interface EntityListProps {
  entityType?: string;
  onSelectEntity?: (entity: Entity) => void;
  selectedEntityId?: string;
}

const ENTITY_TYPE_LABELS: Record<string, string> = {
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

const ENTITY_TYPE_COLORS: Record<string, string> = {
  person: 'bg-blue-100 text-blue-800',
  organization: 'bg-green-100 text-green-800',
  location: 'bg-orange-100 text-orange-800',
  concept: 'bg-purple-100 text-purple-800',
  event: 'bg-red-100 text-red-800',
  product: 'bg-pink-100 text-pink-800',
  project: 'bg-indigo-100 text-indigo-800',
  date: 'bg-gray-100 text-gray-800',
  other: 'bg-gray-100 text-gray-800',
};

export function EntityList({ entityType, onSelectEntity, selectedEntityId }: EntityListProps) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    loadEntities();
  }, [entityType, page, search]);

  const loadEntities = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await api.getEntities(entityType, page, 50, search || undefined);
      if (response.data) {
        const data = response.data as any;
        setEntities(data.entities || []);
        setTotal(data.total || 0);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entities');
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = (value: string) => {
    setSearch(value);
    setPage(1);
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Entities</h2>
        <p className="text-sm text-gray-500">{total} entities found</p>
      </div>

      {/* Search */}
      <div className="p-4 border-b border-gray-200">
        <input
          type="text"
          placeholder="Search entities..."
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>

      {/* Entity List */}
      <div className="max-h-[500px] overflow-y-auto">
        {loading ? (
          <div className="p-8 text-center text-gray-500">Loading entities...</div>
        ) : error ? (
          <div className="p-8 text-center text-red-500">{error}</div>
        ) : entities.length === 0 ? (
          <div className="p-8 text-center text-gray-500">No entities found</div>
        ) : (
          <div className="divide-y divide-gray-200">
            {entities.map((entity) => (
              <div
                key={entity.id}
                onClick={() => onSelectEntity?.(entity)}
                className={`p-4 hover:bg-gray-50 cursor-pointer transition-colors ${
                  selectedEntityId === entity.id ? 'bg-blue-50' : ''
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 truncate">{entity.name}</h3>
                    <div className="mt-1 flex items-center gap-2">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                        ENTITY_TYPE_COLORS[entity.type] || ENTITY_TYPE_COLORS.other
                      }`}>
                        {ENTITY_TYPE_LABELS[entity.type] || entity.type}
                      </span>
                    </div>
                  </div>
                  <div className="ml-4 flex flex-col items-end text-sm text-gray-500">
                    <span>{entity.document_count} docs</span>
                    <span>{entity.relationship_count} rels</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > 50 && (
        <div className="p-4 border-t border-gray-200 flex items-center justify-between">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 border border-gray-300 rounded-md text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
          >
            Previous
          </button>
          <span className="text-sm text-gray-600">
            Page {page} of {Math.ceil(total / 50)}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= Math.ceil(total / 50)}
            className="px-3 py-1 border border-gray-300 rounded-md text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

export default EntityList;
