'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Link as IntlLink } from '@/i18n/routing';

interface SpaceItem {
  id: string;
  name: string;
  description: string | null;
  icon: string | null;
  bucket: string;
  is_pinned: boolean;
  item_count: number;
  created_at: string;
  updated_at: string;
}

interface SpacesResponse {
  spaces: SpaceItem[];
  total: number;
  page: number;
  page_size: number;
}

export default function SpacesPage() {
  const t = useTranslations('spaces');
  const tCommon = useTranslations('common');
  const locale = useLocale();

  const [spaces, setSpaces] = useState<SpaceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);

  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newIcon, setNewIcon] = useState('');
  const [creating, setCreating] = useState(false);

  const fetchSpaces = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = await api.getSpaces(page, 50, searchQuery || undefined);
      if (response.data && !response.error) {
        const data = response.data as SpacesResponse;
        setSpaces(data.spaces);
        setTotal(data.total);
      }
    } catch (error) {
      console.error('Error fetching spaces:', error);
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery]);

  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);

  const handleCreate = async () => {
    if (!newName) return;
    setCreating(true);
    try {
      const { api } = await import('@/lib/api');
      const response = await api.createSpace(newName, newDescription || undefined, newIcon || undefined);
      if (response.data && !response.error) {
        setShowCreateModal(false);
        setNewName(''); setNewDescription(''); setNewIcon('');
        fetchSpaces();
      }
    } catch (error) {
      console.error('Error creating space:', error);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteSpace(id);
      fetchSpaces();
    } catch (error) {
      console.error('Error deleting space:', error);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchSpaces();
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('title')}</h1>
          <button onClick={() => setShowCreateModal(true)} className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors">
            {t('create')}
          </button>
        </div>

        <form onSubmit={handleSearch} className="mb-6">
          <input type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('search_placeholder')}
            className="w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500" />
        </form>

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
          </div>
        ) : spaces.length === 0 ? (
          <p className="text-center text-gray-500 dark:text-gray-400 py-12">{t('empty')}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {spaces.map(space => (
              <div key={space.id} className="relative bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 hover:shadow-md transition-shadow">
                <IntlLink href={`/spaces/${space.id}`} className="block p-4">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-2xl">{space.icon || '📁'}</span>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-gray-900 dark:text-white truncate">{space.name}</h3>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {t('items_count', { count: space.item_count })}
                      </p>
                    </div>
                    {space.is_pinned && <span className="text-amber-500">📌</span>}
                  </div>
                  {space.description && (
                    <p className="text-sm text-gray-600 dark:text-gray-300 line-clamp-2">{space.description}</p>
                  )}
                  <p className="text-xs text-gray-400 mt-3">
                    {new Date(space.updated_at).toLocaleDateString(locale)}
                  </p>
                </IntlLink>
                <button
                  onClick={e => { e.preventDefault(); handleDelete(space.id); }}
                  className="absolute top-4 right-4 text-gray-400 hover:text-red-500 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {total > 50 && (
          <div className="flex justify-center gap-2 mt-6">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&laquo;</button>
            <span className="px-3 py-1 text-gray-600 dark:text-gray-300">{page} / {Math.ceil(total / 50)}</span>
            <button disabled={page >= Math.ceil(total / 50)} onClick={() => setPage(p => p + 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&raquo;</button>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">{t('create')}</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('name_label')} *</label>
                <input type="text" value={newName} onChange={e => setNewName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100" required />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('description_label')}</label>
                <textarea value={newDescription} onChange={e => setNewDescription(e.target.value)} rows={2}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('icon_label')}</label>
                <input type="text" value={newIcon} onChange={e => setNewIcon(e.target.value)} placeholder="📁"
                  className="w-20 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-center text-xl" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700">
                {tCommon('cancel')}
              </button>
              <button onClick={handleCreate} disabled={creating || !newName}
                className="px-4 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50">
                {creating ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
