'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';

interface JournalTag {
  id: string;
  tag_name: string;
  tag_type: string;
  auto_generated: boolean;
}

interface JournalEntry {
  id: string;
  original_filename: string;
  mime_type: string;
  metadata: Record<string, string>;
  tags: JournalTag[];
  created_at: string;
  status: string;
  size: number;
}

export default function JournalPage() {
  const t = useTranslations('journal');
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedTag, setSelectedTag] = useState<string>('');
  const [allTags, setAllTags] = useState<string[]>([]);
  const [expandedEntry, setExpandedEntry] = useState<string | null>(null);
  const PAGE_SIZE = 20;

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
        bucket: 'confidential',
        document_type: 'journal',
      });
      if (debouncedSearch) params.set('search', debouncedSearch);

      const res = await fetch(`/api/v1/documents?${params}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed to fetch');
      const data = await res.json();
      setEntries(data.documents || []);
      setTotal(data.total || 0);

      // Extract unique tags from results
      const tagSet = new Set<string>();
      (data.documents || []).forEach((doc: JournalEntry) => {
        doc.tags?.forEach((tag) => tagSet.add(tag.tag_name));
      });
      setAllTags((prev) => {
        const merged = new Set([...prev, ...tagSet]);
        return Array.from(merged).sort();
      });
    } catch (e) {
      console.error('Error fetching journal entries:', e);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const filteredEntries = selectedTag
    ? entries.filter((e) => e.tags?.some((t) => t.tag_name === selectedTag))
    : entries;

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('fr-FR', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const isImage = (mimeType: string) =>
    mimeType.startsWith('image/');

  const hasMore = page * PAGE_SIZE < total;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
        <p className="text-gray-500 mt-1">{t('subtitle')}</p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder={t('search_placeholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <select
          value={selectedTag}
          onChange={(e) => setSelectedTag(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('all_tags')}</option>
          {allTags.map((tag) => (
            <option key={tag} value={tag}>
              #{tag}
            </option>
          ))}
        </select>
      </div>

      {/* Loading */}
      {loading && (
        <div className="text-center py-12 text-gray-500">{t('loading')}</div>
      )}

      {/* Empty state */}
      {!loading && filteredEntries.length === 0 && (
        <div className="text-center py-12">
          <svg
            className="w-16 h-16 mx-auto text-gray-300 mb-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
            />
          </svg>
          <p className="text-gray-500">
            {debouncedSearch || selectedTag ? t('no_results') : t('empty')}
          </p>
        </div>
      )}

      {/* Timeline */}
      {!loading && filteredEntries.length > 0 && (
        <div className="space-y-4">
          {filteredEntries.map((entry) => {
            const journalText =
              entry.metadata?.journal_text || entry.original_filename;
            const journalTimestamp =
              entry.metadata?.journal_timestamp || entry.created_at;
            const expanded = expandedEntry === entry.id;

            return (
              <div
                key={entry.id}
                className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                onClick={() =>
                  setExpandedEntry(expanded ? null : entry.id)
                }
              >
                {/* Date header */}
                <div className="flex items-center justify-between mb-3">
                  <time className="text-sm font-medium text-blue-600">
                    {formatDate(journalTimestamp)}
                  </time>
                  <span className="text-xs text-gray-400 uppercase">
                    {isImage(entry.mime_type) ? t('entry_photo') : t('entry_text')}
                  </span>
                </div>

                {/* Content */}
                <div className={`text-gray-800 ${expanded ? '' : 'line-clamp-3'}`}>
                  {journalText}
                </div>

                {/* Image thumbnail */}
                {isImage(entry.mime_type) && (
                  <div className="mt-3">
                    <img
                      src={`/api/v1/documents/${entry.id}/content`}
                      alt="Journal photo"
                      className={`rounded-lg ${expanded ? 'max-w-full' : 'max-h-48 object-cover'}`}
                    />
                  </div>
                )}

                {/* Tags */}
                {entry.tags && entry.tags.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {entry.tags.map((tag) => (
                      <span
                        key={tag.id}
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          tag.auto_generated
                            ? 'bg-gray-100 text-gray-600'
                            : 'bg-blue-100 text-blue-700'
                        }`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedTag(
                            selectedTag === tag.tag_name ? '' : tag.tag_name
                          );
                        }}
                      >
                        #{tag.tag_name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {/* Load more */}
          {hasMore && (
            <button
              onClick={() => setPage((p) => p + 1)}
              className="w-full py-3 text-blue-600 font-medium hover:bg-blue-50 rounded-lg transition-colors"
            >
              {t('load_more')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
