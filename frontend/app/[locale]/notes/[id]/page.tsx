'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { useRouter } from '@/i18n/routing';
import { useTranslations, useLocale } from 'next-intl';
import { api } from '@/lib/api';
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

export default function NoteDetailPage() {
  const params = useParams();
  const router = useRouter();
  const locale = useLocale();
  const t = useTranslations('notes');
  const tCommon = useTranslations('common');

  const noteId = params.id as string;

  const [note, setNote] = useState<NoteItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Editor state
  const [showEditor, setShowEditor] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editTags, setEditTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);
  const [saving, setSaving] = useState(false);
  const [activeField, setActiveField] = useState<'title' | 'content'>('content');
  const [pendingAudio, setPendingAudio] = useState<{ blob: Blob; transcript: string } | null>(null);

  const fetchNote = async () => {
    setLoading(true);
    try {
      const res = await api.getNote(noteId);
      if (res.data && !res.error) {
        setNote(res.data as NoteItem);
        setError(null);
      } else {
        setError(res.error || tCommon('error'));
      }
    } catch (e) {
      setError(tCommon('error'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNote();
  }, [noteId]);

  const openEditor = () => {
    if (!note) return;
    setEditTitle(note.title);
    setEditContent(note.content || '');
    setEditTags(note.tags.map(t => ({ tag_name: t.tag_name, tag_type: t.tag_type })));
    setPendingAudio(null);
    setShowEditor(true);
  };

  const handleSave = async () => {
    if (!editTitle || !note) return;
    setSaving(true);
    try {
      await api.updateNote(note.id, { title: editTitle, content: editContent, tags: editTags });
      if (pendingAudio) {
        try {
          await api.uploadNoteAudio(note.id, pendingAudio.blob, pendingAudio.transcript);
        } catch (audioError) {
          console.error('Error uploading note audio:', audioError);
        }
        setPendingAudio(null);
      }
      setShowEditor(false);
      fetchNote();
    } catch (error) {
      console.error('Error saving note:', error);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!note) return;
    if (!confirm(t('delete_confirm'))) return;
    try {
      await api.deleteNote(note.id);
      router.push('/notes');
    } catch (error) {
      console.error('Error deleting note:', error);
    }
  };

  const handleVoiceTranscript = (blob: Blob, transcript: string) => {
    if (activeField === 'title') {
      setEditTitle(prev => prev ? `${prev} ${transcript}` : transcript);
    } else {
      setEditContent(prev => prev ? `${prev}\n\n${transcript}` : transcript);
    }
    setPendingAudio({ blob, transcript });
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-vault-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
      </div>
    );
  }

  if (error || !note) {
    return (
      <div className="min-h-screen bg-vault-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">{error || 'Note not found'}</p>
          <button
            onClick={() => router.push('/notes')}
            className="px-4 py-2 bg-amber-500 text-vault-1000 rounded-lg hover:bg-amber-400 transition-colors font-medium"
          >
            {tCommon('back')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-vault-950">
      <div className="max-w-3xl mx-auto px-4 py-8 pb-20">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <button
            onClick={() => router.push('/notes')}
            className="flex items-center gap-2 text-text-muted hover:text-text-primary transition-colors self-start"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            <span>{tCommon('back')}</span>
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={openEditor}
              className="px-4 py-2 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-lg hover:bg-amber-500/20 transition-colors text-sm font-medium"
            >
              {tCommon('edit')}
            </button>
            <button
              onClick={handleDelete}
              className="px-4 py-2 bg-red-500/10 text-red-400 border border-red-500/20 rounded-lg hover:bg-red-500/20 transition-colors text-sm font-medium"
            >
              {tCommon('delete')}
            </button>
          </div>
        </div>

        {/* Note content */}
        <article className="bg-vault-900/60 border border-white/[0.06] rounded-xl p-6 md:p-10">
          <h1 className="text-2xl md:text-3xl font-bold text-text-primary font-display mb-6">
            {note.title}
          </h1>

          {note.content ? (
            <div className="text-text-primary whitespace-pre-wrap text-base md:text-lg leading-relaxed">
              {note.content}
            </div>
          ) : (
            <p className="text-text-muted italic">{t('no_content')}</p>
          )}

          {note.tags.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-8 pt-6 border-t border-white/[0.06]">
              {note.tags.map(tag => (
                <span
                  key={tag.id}
                  className="px-3 py-1 text-sm rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20"
                >
                  {tag.tag_name}
                </span>
              ))}
            </div>
          )}

          <div className="mt-6 text-sm text-text-muted">
            <span>{new Date(note.created_at).toLocaleDateString(locale)}</span>
            {note.updated_at !== note.created_at && (
              <span> · {t('updated')} {new Date(note.updated_at).toLocaleDateString(locale)}</span>
            )}
          </div>
        </article>
      </div>

      {/* Editor modal */}
      {showEditor && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setShowEditor(false)}>
          <div className="bg-vault-900 border border-white/[0.08] rounded-xl shadow-2xl max-w-2xl w-full p-6 max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <h2 className="text-xl font-bold text-text-primary font-display">
                {tCommon('edit')}
              </h2>
              <button
                onClick={() => setShowEditor(false)}
                className="text-text-muted hover:text-text-primary transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
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
                  rows={12}
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
