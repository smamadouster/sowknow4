/**
 * Entity Detail Component
 *
 * Displays detailed information about an entity including relationships,
 * mentions, and timeline.
 */

'use client';

import React, { useState, useEffect } from 'react';
import api from '@/lib/api';

export interface EntityDetail {
  entity: {
    id: string;
    name: string;
    type: string;
    canonical_id?: string;
    aliases?: string[];
    attributes?: Record<string, any>;
    confidence: number;
    document_count: number;
    relationship_count: number;
  };
  relationships: {
    outgoing: Relationship[];
    incoming: Relationship[];
  };
  mentions: Mention[];
}

export interface Relationship {
  id: string;
  target_id?: string;
  source_id?: string;
  type: string;
  confidence: number;
  document_count: number;
}

export interface Mention {
  id: string;
  document_id: string;
  context?: string;
  page_number?: number;
  confidence: number;
}

interface EntityDetailProps {
  entityId: string;
  onClose?: () => void;
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

const RELATION_TYPE_LABELS: Record<string, string> = {
  works_at: 'Works At',
  founded: 'Founded',
  ceo_of: 'CEO Of',
  employee_of: 'Employee Of',
  client_of: 'Client Of',
  partner_of: 'Partner Of',
  related_to: 'Related To',
  mentioned_with: 'Mentioned With',
  located_in: 'Located In',
  happened_on: 'Happened On',
  created_on: 'Created On',
  references: 'References',
  part_of: 'Part Of',
  owned_by: 'Owned By',
  member_of: 'Member Of',
  other: 'Other',
};

export function EntityDetail({ entityId, onClose }: EntityDetailProps) {
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'relationships' | 'mentions'>('overview');

  useEffect(() => {
    loadDetail();
  }, [entityId]);

  const loadDetail = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await api.getEntity(entityId);
      if (response.data) {
        setDetail(response.data as EntityDetail);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entity details');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="text-center text-gray-500">Loading entity details...</div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="text-center text-red-500">{error || 'Entity not found'}</div>
      </div>
    );
  }

  const { entity, relationships, mentions } = detail;

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900">{entity.name}</h2>
          <p className="text-sm text-gray-500">
            {ENTITY_TYPE_LABELS[entity.type] || entity.type} • {entity.document_count} documents • {entity.relationship_count} relationships
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-full"
          >
            <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex">
          <button
            onClick={() => setActiveTab('overview')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'overview'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Overview
          </button>
          <button
            onClick={() => setActiveTab('relationships')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'relationships'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Relationships ({relationships.outgoing.length + relationships.incoming.length})
          </button>
          <button
            onClick={() => setActiveTab('mentions')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'mentions'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Mentions ({mentions.length})
          </button>
        </nav>
      </div>

      {/* Content */}
      <div className="p-4 max-h-[500px] overflow-y-auto">
        {activeTab === 'overview' && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium text-gray-500 mb-2">Basic Information</h3>
              <dl className="grid grid-cols-2 gap-4">
                <div>
                  <dt className="text-xs text-gray-500">Type</dt>
                  <dd className="text-sm font-medium text-gray-900">
                    {ENTITY_TYPE_LABELS[entity.type] || entity.type}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">Confidence</dt>
                  <dd className="text-sm font-medium text-gray-900">{entity.confidence}%</dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">Documents</dt>
                  <dd className="text-sm font-medium text-gray-900">{entity.document_count}</dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">Relationships</dt>
                  <dd className="text-sm font-medium text-gray-900">{entity.relationship_count}</dd>
                </div>
              </dl>
            </div>

            {entity.aliases && entity.aliases.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-500 mb-2">Aliases</h3>
                <div className="flex flex-wrap gap-2">
                  {entity.aliases.map((alias, i) => (
                    <span
                      key={i}
                      className="px-2 py-1 bg-gray-100 text-gray-700 rounded text-sm"
                    >
                      {alias}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {entity.attributes && Object.keys(entity.attributes).length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-500 mb-2">Attributes</h3>
                <dl className="space-y-2">
                  {Object.entries(entity.attributes).map(([key, value]) => (
                    <div key={key} className="flex">
                      <dt className="w-32 text-xs text-gray-500">{key}</dt>
                      <dd className="text-sm text-gray-900">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          </div>
        )}

        {activeTab === 'relationships' && (
          <div className="space-y-4">
            {/* Outgoing */}
            {relationships.outgoing.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-500 mb-2">Outgoing Relationships</h3>
                <div className="space-y-2">
                  {relationships.outgoing.map((rel) => (
                    <div
                      key={rel.id}
                      className="p-3 border border-gray-200 rounded-md hover:bg-gray-50"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-900">
                            {RELATION_TYPE_LABELS[rel.type] || rel.type}
                          </span>
                          <span className="text-gray-400">→</span>
                          <span className="text-sm text-gray-600">{rel.target_id}</span>
                        </div>
                        <div className="text-xs text-gray-500">
                          {rel.document_count} docs • {rel.confidence}% confidence
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Incoming */}
            {relationships.incoming.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-500 mb-2">Incoming Relationships</h3>
                <div className="space-y-2">
                  {relationships.incoming.map((rel) => (
                    <div
                      key={rel.id}
                      className="p-3 border border-gray-200 rounded-md hover:bg-gray-50"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-gray-600">{rel.source_id}</span>
                          <span className="text-gray-400">→</span>
                          <span className="text-sm font-medium text-gray-900">
                            {RELATION_TYPE_LABELS[rel.type] || rel.type}
                          </span>
                        </div>
                        <div className="text-xs text-gray-500">
                          {rel.document_count} docs • {rel.confidence}% confidence
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {relationships.outgoing.length === 0 && relationships.incoming.length === 0 && (
              <div className="text-center text-gray-500 py-8">No relationships found</div>
            )}
          </div>
        )}

        {activeTab === 'mentions' && (
          <div className="space-y-3">
            {mentions.length > 0 ? (
              mentions.map((mention) => (
                <div
                  key={mention.id}
                  className="p-3 border border-gray-200 rounded-md hover:bg-gray-50"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-500">
                      Document: {mention.document_id}
                      {mention.page_number && ` • Page ${mention.page_number}`}
                    </span>
                    <span className="text-xs text-gray-500">
                      {mention.confidence}% confidence
                    </span>
                  </div>
                  {mention.context && (
                    <p className="text-sm text-gray-700 line-clamp-3">{mention.context}</p>
                  )}
                </div>
              ))
            ) : (
              <div className="text-center text-gray-500 py-8">No mentions found</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default EntityDetail;
