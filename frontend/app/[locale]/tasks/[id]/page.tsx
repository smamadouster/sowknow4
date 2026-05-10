'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useParams, useRouter } from 'next/navigation';
import TagSelector from '@/components/TagSelector';
import DateTimePicker from '@/components/DateTimePicker';

interface TagItem {
  id: string;
  tag_name: string;
  tag_type: string;
}

interface TaskItem {
  id: string;
  title: string;
  description: string | null;
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
  priority: 'low' | 'medium' | 'high';
  due_date: string | null;
  alarm_at: string | null;
  alarm_triggered: boolean;
  notes: string | null;
  bucket: string;
  tags: TagItem[];
  created_at: string;
  updated_at: string;
}

const statusOptions: TaskItem['status'][] = ['pending', 'in_progress', 'completed', 'cancelled'];
const priorityOptions: TaskItem['priority'][] = ['low', 'medium', 'high'];

function statusColor(status: TaskItem['status']) {
  switch (status) {
    case 'pending': return 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20';
    case 'in_progress': return 'bg-blue-500/10 text-blue-400 border-blue-500/20';
    case 'completed': return 'bg-green-500/10 text-green-400 border-green-500/20';
    case 'cancelled': return 'bg-gray-500/10 text-gray-400 border-gray-500/20';
  }
}

function priorityColor(priority: TaskItem['priority']) {
  switch (priority) {
    case 'low': return 'text-green-400';
    case 'medium': return 'text-amber-400';
    case 'high': return 'text-red-400';
  }
}

export default function TaskDetailPage() {
  const t = useTranslations('tasks');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const router = useRouter();
  const params = useParams();
  const taskId = params.id as string;

  const [task, setTask] = useState<TaskItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Edit state
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editStatus, setEditStatus] = useState<TaskItem['status']>('pending');
  const [editPriority, setEditPriority] = useState<TaskItem['priority']>('medium');
  const [editDueDate, setEditDueDate] = useState('');
  const [editAlarmAt, setEditAlarmAt] = useState('');
  const [editNotes, setEditNotes] = useState('');
  const [editTags, setEditTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);

  const fetchTask = async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = await api.getTask(taskId);
      if (response.data && !response.error) {
        const data = response.data as TaskItem;
        setTask(data);
        setEditTitle(data.title);
        setEditDescription(data.description || '');
        setEditStatus(data.status);
        setEditPriority(data.priority);
        setEditDueDate(data.due_date ? data.due_date.slice(0, 16) : '');
        setEditAlarmAt(data.alarm_at ? data.alarm_at.slice(0, 16) : '');
        setEditNotes(data.notes || '');
        setEditTags(data.tags.map(t => ({ tag_name: t.tag_name, tag_type: t.tag_type })));
      }
    } catch (error) {
      console.error('Error fetching task:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchTask(); }, [taskId]);

  const handleSave = async () => {
    if (!editTitle) return;
    setSaving(true);
    setSaveError(null);
    try {
      const { api } = await import('@/lib/api');
      const response = await api.updateTask(taskId, {
        title: editTitle,
        description: editDescription || undefined,
        status: editStatus,
        priority: editPriority,
        due_date: editDueDate || undefined,
        alarm_at: editAlarmAt || undefined,
        notes: editNotes || undefined,
        tags: editTags,
      });
      if (response.error) {
        setSaveError(response.error);
        return;
      }
      setIsEditing(false);
      setSaveError(null);
      await new Promise(r => setTimeout(r, 300));
      await fetchTask();
    } catch (error) {
      console.error('Error saving task:', error);
      setSaveError(tCommon('save_error'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteTask(taskId);
      router.push(`/${locale}/tasks`);
    } catch (error) {
      console.error('Error deleting task:', error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-vault-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
      </div>
    );
  }

  if (!task) {
    return (
      <div className="min-h-screen bg-vault-950 flex items-center justify-center">
        <p className="text-text-muted">Task not found</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-vault-950">
      <div className="max-w-3xl mx-auto px-4 py-8 pb-20 md:pb-8">
        {/* Back + Actions */}
        <div className="flex items-center justify-between mb-6">
          <button
            onClick={() => router.push(`/${locale}/tasks`)}
            className="flex items-center gap-2 text-text-secondary hover:text-text-primary transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            <span className="text-sm font-medium">{tCommon('back')}</span>
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsEditing(!isEditing)}
              className="px-3 py-1.5 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04] transition-colors text-sm"
            >
              {isEditing ? tCommon('cancel') : tCommon('edit')}
            </button>
            <button
              onClick={handleDelete}
              className="px-3 py-1.5 rounded-lg border border-red-500/20 text-red-400 hover:bg-red-500/10 transition-colors text-sm"
            >
              {tCommon('delete')}
            </button>
          </div>
        </div>

        {/* View Mode */}
        {!isEditing && (
          <div className="space-y-6">
            <div>
              <h1 className="text-2xl font-bold text-text-primary font-display">{task.title}</h1>
              {task.description && (
                <p className="text-text-secondary mt-2">{task.description}</p>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              <span className={`px-3 py-1 text-sm rounded-full border ${statusColor(task.status)}`}>
                {t(`status_${task.status}` as any)}
              </span>
              <span className={`px-3 py-1 text-sm font-medium ${priorityColor(task.priority)}`}>
                {t(`priority_${task.priority}` as any)}
              </span>
              {task.alarm_at && !task.alarm_triggered && (
                <span className="px-3 py-1 text-sm text-amber-400 flex items-center gap-1 bg-amber-500/10 rounded-full border border-amber-500/20">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                  </svg>
                  {new Date(task.alarm_at).toLocaleString(locale)}
                </span>
              )}
              {task.alarm_at && task.alarm_triggered && (
                <span className="px-3 py-1 text-sm text-green-400 flex items-center gap-1 bg-green-500/10 rounded-full border border-green-500/20">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  {t('alarm_triggered')}
                </span>
              )}
            </div>

            {task.due_date && (
              <div className="p-4 bg-vault-800/30 rounded-lg border border-white/[0.06]">
                <p className="text-sm text-text-muted">{t('due_date_label')}</p>
                <p className="text-text-primary font-medium">{new Date(task.due_date).toLocaleString(locale)}</p>
              </div>
            )}

            {task.notes && (
              <div className="p-4 bg-vault-800/30 rounded-lg border border-white/[0.06]">
                <p className="text-sm text-text-muted mb-2">{t('notes_label')}</p>
                <p className="text-text-primary whitespace-pre-wrap">{task.notes}</p>
              </div>
            )}

            {task.tags.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {task.tags.map(tag => (
                  <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    {tag.tag_name}
                  </span>
                ))}
              </div>
            )}

            <p className="text-xs text-text-muted">
              {tCommon('updated')}: {new Date(task.updated_at).toLocaleString(locale)}
            </p>
          </div>
        )}

        {/* Edit Mode */}
        {isEditing && (
          <div className="space-y-4">
            {saveError && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                {saveError}
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">{t('title_label')} *</label>
              <input
                type="text"
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">{t('description_label')}</label>
              <textarea
                value={editDescription}
                onChange={e => setEditDescription(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none resize-none"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-text-secondary mb-1">{t('status_label')}</label>
                <select
                  value={editStatus}
                  onChange={e => setEditStatus(e.target.value as TaskItem['status'])}
                  className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
                >
                  {statusOptions.map(s => (
                    <option key={s} value={s}>{t(`status_${s}` as any)}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-text-secondary mb-1">{t('priority_label')}</label>
                <select
                  value={editPriority}
                  onChange={e => setEditPriority(e.target.value as TaskItem['priority'])}
                  className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
                >
                  {priorityOptions.map(p => (
                    <option key={p} value={p}>{t(`priority_${p}` as any)}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <DateTimePicker
                label={t('due_date_label')}
                value={editDueDate}
                onChange={setEditDueDate}
              />
              <DateTimePicker
                label={t('alarm_at_label')}
                value={editAlarmAt}
                onChange={setEditAlarmAt}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">{t('notes_label')}</label>
              <textarea
                value={editNotes}
                onChange={e => setEditNotes(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none resize-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">{t('tags_label')}</label>
              <TagSelector tags={editTags} onChange={setEditTags} />
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <button
                onClick={() => setIsEditing(false)}
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
        )}
      </div>
    </div>
  );
}
