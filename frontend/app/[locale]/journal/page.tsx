'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { formatDate } from '@/lib/formatDate';
import api from '@/lib/api';
import VoiceRecorder from '@/components/VoiceRecorder';

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

interface EntryContent {
  [entryId: string]: string;
}

export default function JournalPage() {
  const t = useTranslations('journal');
  const voiceT = useTranslations('voice');
  const locale = useLocale();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [showRecorder, setShowRecorder] = useState(false);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedTag, setSelectedTag] = useState<string>('');
  const [allTags, setAllTags] = useState<string[]>([]);
  const [expandedEntry, setExpandedEntry] = useState<string | null>(null);
  const [entryContents, setEntryContents] = useState<EntryContent>({});
  const [loadingContent, setLoadingContent] = useState<string | null>(null);
  const [contentSearch, setContentSearch] = useState('');
  const [contentSearchResults, setContentSearchResults] = useState<Map<string, number[]>>(new Map());
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
      const { data } = await api.getDocuments(
        page, PAGE_SIZE, 'confidential', debouncedSearch || undefined,
        undefined, undefined, 'journal', selectedTag || undefined,
      );
      const docs = (data?.documents || []) as unknown as JournalEntry[];
      setEntries(prev => {
        const allDocs = page === 1 ? docs : [...prev, ...docs];
        // Extract unique tags from all loaded entries (for the dropdown)
        const tagSet = new Set<string>();
        allDocs.forEach((doc) => {
          doc.tags?.forEach((tag) => tagSet.add(tag.tag_name));
        });
        setAllTags(Array.from(tagSet).sort());
        return allDocs;
      });
      setTotal(data?.total || 0);
    } catch (e) {
      console.error('Error fetching journal entries:', e);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch, selectedTag]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  // Tag filtering is done server-side via the `tag` query parameter
  const filteredEntries = entries;

  const formatJournalDate = (dateStr: string) =>
    formatDate(dateStr, { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }, 'fr-FR');

  const isImage = (mimeType: string) =>
    mimeType.startsWith('image/');

  const isAudio = (mimeType: string) =>
    mimeType.startsWith('audio/');

  const hasMore = page * PAGE_SIZE < total;

  const fetchEntryContent = useCallback(async (entryId: string) => {
    if (entryContents[entryId] || loadingContent === entryId) return;
    setLoadingContent(entryId);
    try {
      const res = await fetch(`/api/v1/documents/${entryId}/download`, {
        credentials: 'include',
      });
      if (res.ok) {
        const text = await res.text();
        setEntryContents(prev => ({ ...prev, [entryId]: text }));
      }
    } catch (e) {
      console.error('Error fetching entry content:', e);
    } finally {
      setLoadingContent(null);
    }
  }, [entryContents, loadingContent]);

  const handleEntryClick = useCallback((entry: JournalEntry) => {
    const expanded = expandedEntry === entry.id;
    if (!expanded && !isImage(entry.mime_type) && !isAudio(entry.mime_type) && !entryContents[entry.id]) {
      fetchEntryContent(entry.id);
    }
    setExpandedEntry(expanded ? null : entry.id);
  }, [expandedEntry, entryContents, fetchEntryContent]);

  const searchInContent = useCallback((content: string, searchTerm: string): number[] => {
    if (!searchTerm.trim()) return [];
    const results: number[] = [];
    const lowerContent = content.toLowerCase();
    const lowerSearch = searchTerm.toLowerCase();
    let pos = 0;
    while ((pos = lowerContent.indexOf(lowerSearch, pos)) !== -1) {
      results.push(pos);
      pos += 1;
    }
    return results;
  }, []);

  useEffect(() => {
    const newResults = new Map<string, number[]>();
    entries.forEach(entry => {
      const content = entryContents[entry.id];
      if (content && contentSearch) {
        newResults.set(entry.id, searchInContent(content, contentSearch));
      }
    });
    setContentSearchResults(newResults);
  }, [contentSearch, entryContents, entries, searchInContent]);

  const highlightedContent = useMemo(() => {
    if (!contentSearch.trim() || !expandedEntry) return null;
    const content = entryContents[expandedEntry];
    if (!content) return null;
    const results = contentSearchResults.get(expandedEntry) || [];
    if (results.length === 0) return content;
    const parts: React.ReactNode[] = [];
    let lastEnd = 0;
    results.slice(0, 100).forEach((pos) => {
      if (pos > lastEnd) {
        parts.push(content.slice(lastEnd, pos));
      }
      parts.push(
        <mark key={pos} className="bg-yellow-200 rounded px-0.5">{content.slice(pos, pos + contentSearch.length)}</mark>
      );
      lastEnd = pos + contentSearch.length;
    });
    if (lastEnd < content.length) {
      parts.push(content.slice(lastEnd));
    }
    return parts;
  }, [contentSearch, expandedEntry, entryContents, contentSearchResults]);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-gray-500 mt-1">{t('subtitle')}</p>
        </div>
        <button
          onClick={() => setShowRecorder((v) => !v)}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            showRecorder
              ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
              : 'bg-amber-500 text-white hover:bg-amber-600'
          }`}
          title={voiceT('addVoiceEntry')}
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
          </svg>
          {voiceT('addVoiceEntry')}
        </button>
      </div>

      {/* Voice recorder */}
      {showRecorder && (
        <div className="mb-6 p-4 bg-vault-900/50 border border-vault-700 rounded-xl">
          <VoiceRecorder
            mode="journal"
            lang={locale}
            onAudioReady={async (blob, transcript) => {
              try {
                await api.uploadAudioDocument(blob, 'confidential', transcript, 'journal', 'voice-note');
                setShowRecorder(false);
                setPage(1);
                fetchEntries();
              } catch (e) {
                console.error('Error uploading voice entry:', e);
              }
            }}
            onCancel={() => setShowRecorder(false)}
          />
        </div>
      )}

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
          onChange={(e) => { setSelectedTag(e.target.value); setPage(1); }}
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

      {/* Content search */}
      {expandedEntry && entryContents[expandedEntry] && (
        <div className="mb-4 flex items-center gap-3">
          <input
            type="text"
            placeholder={t('search_in_content') || 'Search in document...'}
            value={contentSearch}
            onChange={(e) => setContentSearch(e.target.value)}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
          />
          {contentSearch && (
            <span className="text-sm text-gray-500">
              {(contentSearchResults.get(expandedEntry) || []).length} {t('matches') || 'matches'}
            </span>
          )}
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
            const fullContent = entryContents[entry.id];
            const isLoadingContent = loadingContent === entry.id;

            return (
              <div
                key={entry.id}
                className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                onClick={() => handleEntryClick(entry)}
              >
                {/* Date header */}
                <div className="flex items-center justify-between mb-3">
                  <time className="text-sm font-medium text-blue-600">
                    {formatJournalDate(journalTimestamp)}
                  </time>
                  <span className="text-xs text-gray-400 uppercase">
                    {isImage(entry.mime_type) ? t('entry_photo') : isAudio(entry.mime_type) ? t('entry_audio') : t('entry_text')}
                  </span>
                </div>

                {/* Content */}
                {!expanded && (
                  <div className="text-gray-800 line-clamp-3">
                    {journalText}
                  </div>
                )}

                {expanded && isImage(entry.mime_type) && (
                  <img
                    src={`/api/v1/documents/${entry.id}/content`}
                    alt="Journal photo"
                    className="rounded-lg max-w-full"
                  />
                )}

                {expanded && isAudio(entry.mime_type) && (
                  <div className="mt-2">
                    <audio
                      src={api.getAudioStreamUrl(entry.id)}
                      controls
                      className="w-full"
                    />
                    {entry.metadata?.transcript && (
                      <p className="mt-2 text-sm text-gray-600 italic">{entry.metadata.transcript}</p>
                    )}
                  </div>
                )}

                {expanded && !isImage(entry.mime_type) && !isAudio(entry.mime_type) && (
                  <div>
                    {isLoadingContent ? (
                      <div className="flex items-center gap-2 text-gray-400 py-4">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                        <span className="text-sm">{t('loading')}</span>
                      </div>
                    ) : fullContent ? (
                      <div className="max-h-[60vh] overflow-auto border border-gray-200 rounded-lg bg-gray-50">
                        <pre className="p-4 text-sm text-gray-800 whitespace-pre-wrap break-words font-mono leading-relaxed">
                          {highlightedContent || fullContent}
                        </pre>
                      </div>
                    ) : (
                      <div className="text-gray-800 whitespace-pre-wrap break-words">
                        {journalText}
                      </div>
                    )}
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
                          const newTag = selectedTag === tag.tag_name ? '' : tag.tag_name;
                          setSelectedTag(newTag);
                          setPage(1);
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
