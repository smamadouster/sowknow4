'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import TagSelector from '@/components/TagSelector';
import VoiceRecorder from '@/components/VoiceRecorder';
import { useIsMobile } from '@/hooks/useIsMobile';
import MobileSheet from '@/components/mobile/MobileSheet';
import FAB from '@/components/mobile/FAB';
import SwipeableRow from '@/components/mobile/SwipeableRow';
import PullToRefresh from '@/components/mobile/PullToRefresh';

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
  const isMobile = useIsMobile();

  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [editingNote, setEditingNote] = useState<NoteItem | null>(null);
  const [viewingNote, setViewingNote] = useState<NoteItem | null>(null);

  // Editor state
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editTags, setEditTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);
  const [saving, setSaving] = useState(false);
  const [pendingAudio, setPendingAudio] = useState<{ blob: Blob; transcript: string } | null>(null);
  const [activeField, setActiveField] = useState<'title' | 'content'>('content');

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

  const resetAndNewNote = () => {
    setEditingNote(null);
    setEditTitle('');
    setEditContent('');
    setEditTags([]);
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

  const activeFieldRef = useRef(activeField);
  useEffect(() => { activeFieldRef.current = activeField; }, [activeField]);

  const handleVoiceTranscript = useCallback((blob: Blob, transcript: string) => {
    if (activeFieldRef.current === 'title') {
      setEditTitle(prev => prev ? `${prev} ${transcript}` : transcript);
    } else {
      setEditContent(prev => prev ? `${prev}\n\n${transcript}` : transcript);
    }
    setPendingAudio({ blob, transcript });
  }, []);

  // Read-only viewer body shared between mobile sheet and desktop modal
  const noteViewerBody = viewingNote && (
    <div className="space-y-4">
      {viewingNote.content ? (
        <p className="text-text-primary whitespace-pre-wrap text-sm leading-relaxed">{viewingNote.content}</p>
      ) : (
        <p className="text-text-muted italic text-sm">{t('no_content')}</p>
      )}
      {viewingNote.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-2 border-t border-white/[0.06]">
          {viewingNote.tags.map(tag => (
            <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
              {tag.tag_name}
            </span>
          ))}
        </div>
      )}
      <p className="text-xs text-text-muted">
        {new Date(viewingNote.created_at).toLocaleDateString(locale)}
        {viewingNote.updated_at !== viewingNote.created_at && (
          <> · {t('updated')} {new Date(viewingNote.updated_at).toLocaleDateString(locale)}</>
        )}
      </p>
    </div>
  );

  // Editor content shared between mobile sheet and desktop modal
  const editorContent = (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('title_label')} *</label>
        <input
          type="text"
          value={editTitle}
          onChange={e => setEditTitle(e.target.value)}
          onFocus={() => setActiveField('title')}
          autoFocus
          className={`w-full px-3 py-2 rounded-lg border bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none ${
            activeField === 'title' ? 'border-amber-500/30' : 'border-white/[0.08]'
          }`}
          required
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('content_label')}</label>
        <textarea
          value={editContent}
          onChange={e => setEditContent(e.target.value)}
          onFocus={() => setActiveField('content')}
          rows={10}
          className={`w-full px-3 py-2 rounded-lg border bg-vault-800/50 text-text-primary placeholder-text-muted/50 font-mono text-sm focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none resize-none ${
            activeField === 'content' ? 'border-amber-500/30' : 'border-white/[0.08]'
          }`}
        />
      </div>
      <div className="p-3 bg-vault-800/30 rounded-lg border border-white/[0.06]">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs text-text-muted">
            {activeField === 'title' ? t('title_label') : t('content_label')}
          </span>
          <span className="text-xs text-amber-400/60">{t('dictation_target')}</span>
        </div>
        <VoiceRecorder
          mode="note"
          lang={locale}
          onAudioReady={handleVoiceTranscript}
        />
      </div>
      {pendingAudio && (
        <p className="text-xs text-amber-400">
          {t('audio_pending')}
        </p>
      )}
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('tags_label')}</label>
        <TagSelector tags={editTags} onChange={setEditTags} />
      </div>
    </div>
  );

  const notesList = (
    <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
      {notes.map(note => {
        const card = (
          <div
            className="p-4 bg-vault-900/60 rounded-lg border border-white/[0.06] cursor-pointer hover:border-white/[0.12] hover:bg-vault-900/80 transition-all"
            onClick={() => setViewingNote(note)}
          >
            <div className="flex items-start justify-between">
              <h3 className="font-medium text-text-primary truncate flex-1">{note.title}</h3>
              {/* Trash button: hidden on mobile (replaced by swipe) */}
              <button
                onClick={e => { e.stopPropagation(); handleDelete(note.id); }}
                className="hidden md:flex ml-2 text-text-muted hover:text-red-400 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
            {note.content && (
              <p className="text-sm text-text-secondary mt-2 line-clamp-3">{note.content}</p>
            )}
            <div className="flex flex-wrap gap-1 mt-3">
              {note.tags.map(tag => (
                <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  {tag.tag_name}
                </span>
              ))}
            </div>
            <p className="text-xs text-text-muted mt-2">
              {new Date(note.created_at).toLocaleDateString(locale)}
            </p>
          </div>
        );

        return isMobile ? (
          <SwipeableRow
            key={note.id}
            onSwipeAction={() => handleDelete(note.id)}
            actionLabel={tCommon('delete')}
            actionColor="bg-red-600"
          >
            {card}
          </SwipeableRow>
        ) : (
          <div key={note.id}>{card}</div>
        );
      })}
    </div>
  );

  return (
    <div className="min-h-screen bg-vault-950">
      <div className="max-w-6xl mx-auto px-4 py-8 pb-20 md:pb-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-text-primary font-display">{t('title')}</h1>
          <button
            onClick={() => openEditor()}
            className="hidden md:inline-flex px-4 py-2 bg-amber-500 text-vault-1000 rounded-lg hover:bg-amber-400 transition-colors font-medium"
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
            className="w-full px-4 py-3 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          />
        </form>

        {/* Loading / Empty / Grid */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
          </div>
        ) : notes.length === 0 ? (
          <p className="text-center text-text-muted py-12">{t('empty')}</p>
        ) : isMobile ? (
          <PullToRefresh onRefresh={fetchNotes}>
            {notesList}
          </PullToRefresh>
        ) : (
          notesList
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

      {/* Read-only Note View — Mobile: MobileSheet */}
      {isMobile && viewingNote && (
        <MobileSheet
          open={!!viewingNote}
          onClose={() => setViewingNote(null)}
          title={viewingNote.title}
          headerActions={
            <button
              onClick={() => { openEditor(viewingNote); setViewingNote(null); }}
              className="text-xs text-amber-400 hover:text-amber-300 transition-colors px-2 py-1 rounded"
            >
              {tCommon('edit')}
            </button>
          }
          footer={
            <div className="flex gap-3">
              <button
                onClick={() => setViewingNote(null)}
                className="flex-1 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors font-medium"
                style={{ minHeight: '44px' }}
              >
                {tCommon('close')}
              </button>
              <button
                onClick={() => { openEditor(viewingNote); setViewingNote(null); }}
                className="flex-1 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 font-medium transition-colors"
                style={{ minHeight: '44px' }}
              >
                {tCommon('edit')}
              </button>
            </div>
          }
        >
          {noteViewerBody}
        </MobileSheet>
      )}

      {/* Read-only Note View — Desktop: Modal */}
      {!isMobile && viewingNote && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setViewingNote(null)}>
          <div className="bg-vault-900 border border-white/[0.08] rounded-xl shadow-2xl max-w-lg w-full p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <h2 className="text-xl font-bold text-text-primary font-display">{viewingNote.title}</h2>
              <button
                onClick={() => setViewingNote(null)}
                className="text-text-muted hover:text-text-primary transition-colors ml-2"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            {noteViewerBody}
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setViewingNote(null)}
                className="px-4 py-2 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors"
              >
                {tCommon('close')}
              </button>
              <button
                onClick={() => { openEditor(viewingNote); setViewingNote(null); }}
                className="px-4 py-2 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 font-medium transition-colors"
              >
                {tCommon('edit')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* FAB — mobile only */}
      <FAB onClick={resetAndNewNote} label={t('new')} />

      {/* Editor — Mobile: MobileSheet */}
      {isMobile && (
        <MobileSheet
          open={showEditor}
          onClose={() => setShowEditor(false)}
          title={editingNote ? editingNote.title : t('new')}
          headerActions={
            editingNote ? (
              <button
                onClick={resetAndNewNote}
                className="text-xs text-amber-400 hover:text-amber-300 transition-colors px-2 py-1 rounded"
              >
                {t('new')}
              </button>
            ) : undefined
          }
          footer={
            <div className="flex gap-3">
              <button
                onClick={() => setShowEditor(false)}
                className="flex-1 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors font-medium"
                style={{ minHeight: '44px' }}
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !editTitle}
                className="flex-1 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 disabled:opacity-50 font-medium transition-colors"
                style={{ minHeight: '44px' }}
              >
                {saving ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          }
        >
          {editorContent}
        </MobileSheet>
      )}

      {/* Editor — Desktop: Modal */}
      {!isMobile && showEditor && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-vault-900 border border-white/[0.08] rounded-xl shadow-2xl max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-text-primary font-display mb-4">
              {editingNote ? editingNote.title : t('new')}
            </h2>
            {editorContent}
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowEditor(false)}
                className="px-4 py-2 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !editTitle}
                className="px-4 py-2 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-400 disabled:opacity-50 font-medium transition-colors"
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
