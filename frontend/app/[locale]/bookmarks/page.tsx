'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import TagSelector from '@/components/TagSelector';
import { useIsMobile } from '@/hooks/useIsMobile';
import MobileSheet from '@/components/mobile/MobileSheet';
import FAB from '@/components/mobile/FAB';
import SwipeableRow from '@/components/mobile/SwipeableRow';
import { parseDomain } from './utils';

interface TagItem {
  id: string;
  tag_name: string;
  tag_type: string;
}

interface Bookmark {
  id: string;
  url: string;
  title: string;
  description: string | null;
  favicon_url: string | null;
  bucket: string;
  tags: TagItem[];
  created_at: string;
  updated_at: string;
}

interface BookmarksResponse {
  bookmarks: Bookmark[];
  total: number;
  page: number;
  page_size: number;
}

export default function BookmarksPage() {
  const t = useTranslations('bookmarks');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const isMobile = useIsMobile();

  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateSheet, setShowCreateSheet] = useState(false);

  // Create form state
  const [newUrl, setNewUrl] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newTags, setNewTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);
  const [creating, setCreating] = useState(false);

  const fetchBookmarks = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = searchQuery
        ? await api.searchBookmarks(searchQuery, page, 50)
        : await api.getBookmarks(page, 50);
      if (response.data && !response.error) {
        const data = response.data as BookmarksResponse;
        setBookmarks(data.bookmarks);
        setTotal(data.total);
      }
    } catch (error) {
      console.error('Error fetching bookmarks:', error);
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery]);

  useEffect(() => { fetchBookmarks(); }, [fetchBookmarks]);

  const resetForm = () => {
    setNewUrl(''); setNewTitle(''); setNewDescription(''); setNewTags([]);
  };

  const handleCreate = async () => {
    if (!newUrl || newTags.length === 0) return;
    setCreating(true);
    try {
      const { api } = await import('@/lib/api');
      const response = await api.createBookmark(newUrl, newTags, newTitle || undefined, newDescription || undefined);
      if (response.data && !response.error) {
        setShowCreateSheet(false);
        resetForm();
        fetchBookmarks();
      }
    } catch (error) {
      console.error('Error creating bookmark:', error);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteBookmark(id);
      fetchBookmarks();
    } catch (error) {
      console.error('Error deleting bookmark:', error);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchBookmarks();
  };

  // Shared create form content (used in both MobileSheet and desktop modal)
  const createFormContent = (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">URL *</label>
        <input
          type="url"
          value={newUrl}
          onChange={e => setNewUrl(e.target.value)}
          placeholder={t('url_placeholder')}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          required
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('title_label')}</label>
        <input
          type="text"
          value={newTitle}
          onChange={e => setNewTitle(e.target.value)}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('description_label')}</label>
        <textarea
          value={newDescription}
          onChange={e => setNewDescription(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none resize-none"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('tags_label')}</label>
        <TagSelector tags={newTags} onChange={setNewTags} required />
      </div>
    </div>
  );

  const bookmarkCard = (bookmark: Bookmark) => (
    <div
      className="p-4 bg-vault-900/60 rounded-xl border border-white/[0.06] hover:border-white/[0.12] hover:bg-vault-900/80 transition-all"
    >
      <div className="flex items-start gap-3 min-w-0">
        {bookmark.favicon_url ? (
          <img src={bookmark.favicon_url} alt="" width={16} height={16} className="w-4 h-4 rounded mt-0.5 shrink-0" />
        ) : (
          <div className="w-4 h-4 rounded bg-amber-500/20 shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-xs text-text-muted truncate mb-0.5">{parseDomain(bookmark.url)}</p>
          <a
            href={bookmark.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            className="text-sm font-semibold text-text-primary hover:text-amber-400 transition-colors line-clamp-2 block leading-snug"
          >
            {bookmark.title}
          </a>
          {bookmark.description && (
            <p className="text-xs text-text-secondary mt-1 line-clamp-2">{bookmark.description}</p>
          )}
          <div className="flex flex-wrap gap-1 mt-2">
            {bookmark.tags.map(tag => (
              <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                {tag.tag_name}
              </span>
            ))}
          </div>
          <p className="text-xs text-text-muted mt-2">
            {new Date(bookmark.created_at).toLocaleDateString(locale)}
          </p>
        </div>
        {/* Delete button: hidden on mobile (replaced by swipe-to-delete) */}
        <button
          onClick={() => handleDelete(bookmark.id)}
          className="hidden md:inline-flex text-text-muted hover:text-red-400 transition-colors shrink-0 mt-0.5"
          aria-label={tCommon('delete')}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-vault-950 overflow-x-hidden">
      <div className="max-w-6xl mx-auto px-4 py-8 pb-20 md:pb-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-text-primary font-display">{t('title')}</h1>
          <button
            onClick={() => setShowCreateSheet(true)}
            className="hidden md:inline-flex px-4 py-2 bg-amber-500 text-vault-1000 rounded-lg hover:bg-amber-400 transition-colors font-medium"
          >
            {t('add')}
          </button>
        </div>

        {/* Search */}
        <form onSubmit={handleSearch} className="mb-6">
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('search_placeholder')}
            className="w-full px-4 py-3 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          />
        </form>

        {/* Loading / Empty / List */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
          </div>
        ) : bookmarks.length === 0 ? (
          <p className="text-center text-text-muted py-12">{t('empty')}</p>
        ) : (
          <div className="grid gap-3">
            {bookmarks.map(bookmark =>
              isMobile ? (
                <SwipeableRow
                  key={bookmark.id}
                  onSwipeAction={() => handleDelete(bookmark.id)}
                  actionLabel={tCommon('delete')}
                  actionColor="bg-red-600"
                >
                  {bookmarkCard(bookmark)}
                </SwipeableRow>
              ) : (
                <div key={bookmark.id}>{bookmarkCard(bookmark)}</div>
              )
            )}
          </div>
        )}

        {/* Pagination */}
        {total > 50 && (
          <div className="flex justify-center gap-2 mt-6">
            <button
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 rounded bg-vault-800/60 border border-white/[0.08] text-text-secondary disabled:opacity-50"
            >
              &laquo;
            </button>
            <span className="px-3 py-1 text-text-secondary">{page} / {Math.ceil(total / 50)}</span>
            <button
              disabled={page >= Math.ceil(total / 50)}
              onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 rounded bg-vault-800/60 border border-white/[0.08] text-text-secondary disabled:opacity-50"
            >
              &raquo;
            </button>
          </div>
        )}
      </div>

      {/* FAB — mobile only */}
      {isMobile && <FAB onClick={() => setShowCreateSheet(true)} label={t('add')} />}

      {/* Create — Mobile: MobileSheet */}
      {isMobile && (
        <MobileSheet
          open={showCreateSheet}
          onClose={() => { setShowCreateSheet(false); resetForm(); }}
          title={t('add')}
          footer={
            <div className="flex gap-3">
              <button
                onClick={() => { setShowCreateSheet(false); resetForm(); }}
                className="flex-1 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors font-medium"
                style={{ minHeight: '44px' }}
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !newUrl || newTags.length === 0}
                className="flex-1 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 disabled:opacity-50 font-medium transition-colors"
                style={{ minHeight: '44px' }}
              >
                {creating ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          }
        >
          {createFormContent}
        </MobileSheet>
      )}

      {/* Create — Desktop: Modal */}
      {!isMobile && showCreateSheet && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-vault-900 border border-white/[0.08] rounded-xl shadow-2xl max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-text-primary font-display mb-4">{t('add')}</h2>
            {createFormContent}
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => { setShowCreateSheet(false); resetForm(); }}
                className="px-4 py-2 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !newUrl || newTags.length === 0}
                className="px-4 py-2 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 disabled:opacity-50 font-medium transition-colors"
              >
                {creating ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
