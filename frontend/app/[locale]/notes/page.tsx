'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import TagSelector from '@/components/TagSelector';
import VoiceRecorder from '@/components/VoiceRecorder';

interface TagItem {
  id: string;
  tag_name: string;
  tag_type: string;
}

interface NoteItem {
  id: string;
  title: string;
  content: string | null;
  bucket: string;
  tags: TagItem[];
  created_at: string;
  updated_at: string;
}

interface NotesResponse {
  notes: NoteItem[];
  total: number;
  page: number;
  page_size: number;
}

export default function NotesPage() {
  const t = useTranslations('notes');
  const tCommon = useTranslations('common');
  const locale = useLocale();

  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [editingNote, setEditingNote] = useState<NoteItem | null>(null);

  // Editor state
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editTags, setEditTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);
  const [saving, setSaving] = useState(false);
  const [pendingAudio, setPendingAudio] = useState<{ blob: Blob; transcript: string } | null>(null);

  const fetchNotes = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = searchQuery
        ? await api.searchNotes(searchQuery, page, 50)
        : await api.getNotes(page, 50);
      if (response.data && !response.error) {
        const data = response.data as NotesResponse;
        setNotes(data.notes);
        setTotal(data.total);
      }
    } catch (error) {
      console.error('Error fetching notes:', error);
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery]);

  useEffect(() => { fetchNotes(); }, [fetchNotes]);

  const openEditor = (note?: NoteItem) => {
    if (note) {
      setEditingNote(note);
      setEditTitle(note.title);
      setEditContent(note.content || '');
      setEditTags(note.tags.map(t => ({ tag_name: t.tag_name, tag_type: t.tag_type })));
    } else {
      setEditingNote(null);
      setEditTitle('');
      setEditContent('');
      setEditTags([]);
    }
    setPendingAudio(null);
    setShowEditor(true);
  };

  const handleSave = async () => {
    if (!editTitle) return;
    setSaving(true);
    try {
      const { api } = await import('@/lib/api');
      let savedNoteId: string | null = null;
      if (editingNote) {
        await api.updateNote(editingNote.id, { title: editTitle, content: editContent, tags: editTags });
        savedNoteId = editingNote.id;
      } else {
        const res = await api.createNote(editTitle, editContent || undefined, editTags);
        savedNoteId = (res.data as { id?: string })?.id ?? null;
      }
      if (savedNoteId && pendingAudio) {
        try {
          await api.uploadNoteAudio(savedNoteId, pendingAudio.blob, pendingAudio.transcript);
        } catch (audioError) {
          console.error('Error uploading note audio:', audioError);
        }
        setPendingAudio(null);
      }
      setShowEditor(false);
      fetchNotes();
    } catch (error) {
      console.error('Error saving note:', error);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteNote(id);
      fetchNotes();
    } catch (error) {
      console.error('Error deleting note:', error);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchNotes();
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('title')}</h1>
          <button
            onClick={() => openEditor()}
            className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors"
          >
            {t('new')}
          </button>
        </div>

        {/* Search */}
        <form onSubmit={handleSearch} className="mb-6">
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('search_placeholder')}
            className="w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500"
          />
        </form>

        {/* Loading / Empty / Grid */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
          </div>
        ) : notes.length === 0 ? (
          <p className="text-center text-gray-500 dark:text-gray-400 py-12">{t('empty')}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {notes.map(note => (
              <div
                key={note.id}
                className="p-4 bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 cursor-pointer hover:shadow-md transition-shadow"
                onClick={() => openEditor(note)}
              >
                <div className="flex items-start justify-between">
                  <h3 className="font-medium text-gray-900 dark:text-white truncate flex-1">{note.title}</h3>
                  <button
                    onClick={e => { e.stopPropagation(); handleDelete(note.id); }}
                    className="ml-2 text-gray-400 hover:text-red-500 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
                {note.content && (
                  <p className="text-sm text-gray-600 dark:text-gray-300 mt-2 line-clamp-3">{note.content}</p>
                )}
                <div className="flex flex-wrap gap-1 mt-3">
                  {note.tags.map(tag => (
                    <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">
                      {tag.tag_name}
                    </span>
                  ))}
                </div>
                <p className="text-xs text-gray-400 mt-2">
                  {new Date(note.created_at).toLocaleDateString(locale)}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {total > 50 && (
          <div className="flex justify-center gap-2 mt-6">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&laquo;</button>
            <span className="px-3 py-1 text-gray-600 dark:text-gray-300">{page} / {Math.ceil(total / 50)}</span>
            <button disabled={page >= Math.ceil(total / 50)} onClick={() => setPage(p => p + 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&raquo;</button>
          </div>
        )}
      </div>

      {/* Editor Modal */}
      {showEditor && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              {editingNote ? editingNote.title : t('new')}
            </h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('title_label')} *</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('content_label')}</label>
                <textarea
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                  rows={8}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 font-mono text-sm"
                />
                <div className="mt-2 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600">
                  <VoiceRecorder
                    mode="note"
                    onAudioReady={(blob, transcript) => {
                      setEditContent(prev => prev ? `${prev}\n\n${transcript}` : transcript);
                      setPendingAudio({ blob, transcript });
                    }}
                  />
                </div>
                {pendingAudio && (
                  <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                    {t('audio_pending')}
                  </p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('tags_label')}</label>
                <TagSelector tags={editTags} onChange={setEditTags} />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowEditor(false)}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !editTitle}
                className="px-4 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
              >
                {saving ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
