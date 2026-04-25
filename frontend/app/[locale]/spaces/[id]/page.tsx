'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useParams } from 'next/navigation';

interface TagItem { id: string; tag_name: string; tag_type: string; }

interface SpaceItemData {
  id: string;
  space_id: string;
  item_type: string;
  document_id: string | null;
  bookmark_id: string | null;
  note_id: string | null;
  added_by: string;
  added_at: string;
  note: string | null;
  is_excluded: boolean;
  item_title: string | null;
  item_url: string | null;
  item_tags: TagItem[];
}

interface SpaceRuleData {
  id: string;
  space_id: string;
  rule_type: string;
  rule_value: string;
  is_active: boolean;
  match_count: number;
  created_at: string;
}

interface SpaceDetail {
  id: string;
  name: string;
  description: string | null;
  icon: string | null;
  bucket: string;
  is_pinned: boolean;
  item_count: number;
  items: SpaceItemData[];
  rules: SpaceRuleData[];
  created_at: string;
  updated_at: string;
}

export default function SpaceDetailPage() {
  const t = useTranslations('spaces');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const params = useParams();
  const spaceId = params.id as string;

  const [space, setSpace] = useState<SpaceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'items' | 'rules'>('items');
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [syncing, setSyncing] = useState(false);

  // Rule form
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [newRuleType, setNewRuleType] = useState<'tag' | 'keyword'>('tag');
  const [newRuleValue, setNewRuleValue] = useState('');

  const fetchSpace = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = await api.getSpace(spaceId, typeFilter || undefined);
      if (response.data && !response.error) {
        setSpace(response.data as SpaceDetail);
      }
    } catch (error) {
      console.error('Error fetching space:', error);
    } finally {
      setLoading(false);
    }
  }, [spaceId, typeFilter]);

  useEffect(() => { fetchSpace(); }, [fetchSpace]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { api } = await import('@/lib/api');
      await api.syncSpace(spaceId);
      // Wait a moment then refresh
      setTimeout(() => { fetchSpace(); setSyncing(false); }, 3000);
    } catch (error) {
      console.error('Error syncing space:', error);
      setSyncing(false);
    }
  };

  const handleRemoveItem = async (itemId: string) => {
    try {
      const { api } = await import('@/lib/api');
      await api.removeSpaceItem(spaceId, itemId);
      fetchSpace();
    } catch (error) {
      console.error('Error removing item:', error);
    }
  };

  const handleAddRule = async () => {
    if (!newRuleValue) return;
    try {
      const { api } = await import('@/lib/api');
      await api.addSpaceRule(spaceId, newRuleType, newRuleValue);
      setNewRuleValue('');
      setShowRuleForm(false);
      fetchSpace();
    } catch (error) {
      console.error('Error adding rule:', error);
    }
  };

  const handleToggleRule = async (ruleId: string, isActive: boolean) => {
    try {
      const { api } = await import('@/lib/api');
      await api.updateSpaceRule(spaceId, ruleId, { is_active: !isActive });
      fetchSpace();
    } catch (error) {
      console.error('Error toggling rule:', error);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    try {
      const { api } = await import('@/lib/api');
      await api.deleteSpaceRule(spaceId, ruleId);
      fetchSpace();
    } catch (error) {
      console.error('Error deleting rule:', error);
    }
  };

  const filteredItems = space?.items.filter(item => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (item.item_title || '').toLowerCase().includes(q) ||
      item.item_tags.some(t => t.tag_name.toLowerCase().includes(q));
  }) || [];

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex justify-center items-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
      </div>
    );
  }

  if (!space) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex justify-center items-center">
        <p className="text-gray-500">Space not found</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-4 mb-6">
          <div className="flex items-center gap-3">
            <span className="text-3xl">{space.icon || '📁'}</span>
            <div className="flex-1 min-w-0">
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white truncate">{space.name}</h1>
              {space.description && (
                <p className="text-gray-600 dark:text-gray-300 mt-1 text-sm">{space.description}</p>
              )}
            </div>
          </div>
          <span className="text-sm text-gray-500 dark:text-gray-400 sm:ml-auto">
            {t('items_count', { count: space.item_count })}
          </span>
        </div>

        {/* Tabs */}
        <div className="flex gap-4 border-b border-gray-200 dark:border-gray-700 mb-6">
          <button
            onClick={() => setActiveTab('items')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'items' ? 'border-amber-500 text-amber-600 dark:text-amber-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            {t('items_tab')}
          </button>
          <button
            onClick={() => setActiveTab('rules')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'rules' ? 'border-amber-500 text-amber-600 dark:text-amber-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            {t('rules_tab')} ({space.rules.length})
          </button>
        </div>

        {/* Items Tab */}
        {activeTab === 'items' && (
          <div>
            {/* Search + Filters */}
            <div className="flex flex-wrap gap-3 mb-4">
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder={t('search_items_placeholder')}
                className="flex-1 min-w-[200px] px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              />
              {[null, 'document', 'bookmark', 'note'].map(ft => (
                <button
                  key={ft || 'all'}
                  onClick={() => setTypeFilter(ft)}
                  className={`px-3 py-2 rounded-lg text-sm ${
                    typeFilter === ft ? 'bg-amber-500 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300'
                  }`}
                >
                  {ft === null ? t('filter_all') : t(`filter_${ft}s`)}
                </button>
              ))}
            </div>

            {/* Items List */}
            {filteredItems.length === 0 ? (
              <p className="text-center text-gray-500 dark:text-gray-400 py-8">{t('no_items')}</p>
            ) : (
              <div className="space-y-3">
                {filteredItems.map(item => (
                  <div key={item.id} className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      {/* Type icon */}
                      <span className="text-lg">
                        {item.item_type === 'document' ? '📄' : item.item_type === 'bookmark' ? '🔗' : '📝'}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-gray-900 dark:text-white truncate">
                          {item.item_url ? (
                            <a href={item.item_url} target="_blank" rel="noopener noreferrer" className="hover:underline text-amber-600 dark:text-amber-400">
                              {item.item_title || 'Untitled'}
                            </a>
                          ) : (
                            item.item_title || 'Untitled'
                          )}
                        </p>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {item.item_tags.map(tag => (
                            <span key={tag.id} className="px-1.5 py-0.5 text-xs rounded bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">
                              {tag.tag_name}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 sm:flex-shrink-0">
                      <span className={`text-xs px-2 py-1 rounded ${
                        item.added_by === 'rule' ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                      }`}>
                        {item.added_by === 'rule' ? t('added_by_rule') : t('added_by_user')}
                      </span>
                      <button
                        onClick={() => handleRemoveItem(item.id)}
                        className="text-gray-400 hover:text-red-500"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Rules Tab */}
        {activeTab === 'rules' && (
          <div>
            <div className="flex flex-wrap gap-3 mb-4">
              <button onClick={() => setShowRuleForm(true)}
                className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600">
                {t('add_rule')}
              </button>
              <button onClick={handleSync} disabled={syncing}
                className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50">
                {syncing ? t('syncing') : t('sync_now')}
              </button>
            </div>

            {/* Add Rule Form */}
            {showRuleForm && (
              <div className="p-4 mb-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                <div className="flex flex-col sm:flex-row gap-3">
                  <select
                    value={newRuleType}
                    onChange={e => setNewRuleType(e.target.value as 'tag' | 'keyword')}
                    className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  >
                    <option value="tag">{t('rule_tag')}</option>
                    <option value="keyword">{t('rule_keyword')}</option>
                  </select>
                  <input
                    type="text"
                    value={newRuleValue}
                    onChange={e => setNewRuleValue(e.target.value)}
                    placeholder={t('rule_value_placeholder')}
                    className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  />
                  <button onClick={handleAddRule} disabled={!newRuleValue}
                    className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50">
                    {tCommon('save')}
                  </button>
                  <button onClick={() => { setShowRuleForm(false); setNewRuleValue(''); }}
                    className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300">
                    {tCommon('cancel')}
                  </button>
                </div>
              </div>
            )}

            {/* Rules List */}
            {space.rules.length === 0 ? (
              <p className="text-center text-gray-500 dark:text-gray-400 py-8">No rules defined yet.</p>
            ) : (
              <div className="space-y-3">
                {space.rules.map(rule => (
                  <div key={rule.id} className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <span className={`text-xs px-2 py-1 rounded font-mono flex-shrink-0 ${
                        rule.rule_type === 'tag' ? 'bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300' : 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300'
                      }`}>
                        {rule.rule_type}
                      </span>
                      <span className="flex-1 text-gray-900 dark:text-white font-medium truncate">{rule.rule_value}</span>
                    </div>
                    <div className="flex items-center gap-2 sm:flex-shrink-0">
                      <span className="text-sm text-gray-500">{rule.match_count} matches</span>
                      <button
                        onClick={() => handleToggleRule(rule.id, rule.is_active)}
                        className={`px-3 py-1 rounded text-sm ${
                          rule.is_active ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300' : 'bg-gray-200 dark:bg-gray-700 text-gray-500'
                        }`}
                      >
                        {rule.is_active ? 'Active' : 'Inactive'}
                      </button>
                      <button onClick={() => handleDeleteRule(rule.id)} className="text-gray-400 hover:text-red-500">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
