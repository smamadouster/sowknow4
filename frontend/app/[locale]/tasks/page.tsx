'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from 'next/navigation';
import TagSelector from '@/components/TagSelector';
import DateTimePicker from '@/components/DateTimePicker';
import { useIsMobile } from '@/hooks/useIsMobile';
import { useDebounce } from '@/hooks/useDebounce';
import MobileSheet from '@/components/mobile/MobileSheet';
import FAB from '@/components/mobile/FAB';
import SwipeableRow from '@/components/mobile/SwipeableRow';
import PullToRefresh from '@/components/mobile/PullToRefresh';

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

interface TasksResponse {
  tasks: TaskItem[];
  total: number;
  page: number;
  page_size: number;
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

export default function TasksPage() {
  const t = useTranslations('tasks');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const isMobile = useIsMobile();
  const router = useRouter();

  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const debouncedSearchQuery = useDebounce(searchQuery, 400);
  const [showEditor, setShowEditor] = useState(false);
  const [editingTask, setEditingTask] = useState<TaskItem | null>(null);

  // Editor state
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editStatus, setEditStatus] = useState<TaskItem['status']>('pending');
  const [editPriority, setEditPriority] = useState<TaskItem['priority']>('medium');
  const [editDueDate, setEditDueDate] = useState('');
  const [editAlarmAt, setEditAlarmAt] = useState('');
  const [editNotes, setEditNotes] = useState('');
  const [editTags, setEditTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = debouncedSearchQuery
        ? await api.searchTasks(debouncedSearchQuery, page, 50)
        : await api.getTasks(page, 50);
      if (response.data && !response.error) {
        const data = response.data as TasksResponse;
        setTasks(data.tasks);
        setTotal(data.total);
      }
    } catch (error) {
      console.error('Error fetching tasks:', error);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearchQuery]);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);

  const openEditor = (task?: TaskItem) => {
    if (task) {
      setEditingTask(task);
      setEditTitle(task.title);
      setEditDescription(task.description || '');
      setEditStatus(task.status);
      setEditPriority(task.priority);
      setEditDueDate(task.due_date ? task.due_date.slice(0, 16) : '');
      setEditAlarmAt(task.alarm_at ? task.alarm_at.slice(0, 16) : '');
      setEditNotes(task.notes || '');
      setEditTags(task.tags.map(t => ({ tag_name: t.tag_name, tag_type: t.tag_type })));
    } else {
      setEditingTask(null);
      setEditTitle('');
      setEditDescription('');
      setEditStatus('pending');
      setEditPriority('medium');
      setEditDueDate('');
      setEditAlarmAt('');
      setEditNotes('');
      setEditTags([]);
    }
    setShowEditor(true);
  };

  const resetAndNewTask = () => {
    setEditingTask(null);
    setEditTitle('');
    setEditDescription('');
    setEditStatus('pending');
    setEditPriority('medium');
    setEditDueDate('');
    setEditAlarmAt('');
    setEditNotes('');
    setEditTags([]);
    setShowEditor(true);
  };

  const handleSave = async () => {
    if (!editTitle) return;
    setSaving(true);
    setSaveError(null);
    try {
      const { api } = await import('@/lib/api');
      const payload = {
        title: editTitle,
        description: editDescription || undefined,
        status: editStatus,
        priority: editPriority,
        due_date: editDueDate || undefined,
        alarm_at: editAlarmAt || undefined,
        notes: editNotes || undefined,
        tags: editTags,
      };
      const response = editingTask
        ? await api.updateTask(editingTask.id, payload)
        : await api.createTask(payload);
      if (response.error) {
        setSaveError(response.error);
        return;
      }
      setShowEditor(false);
      setSaveError(null);
      // Small delay to ensure backend transaction is committed
      await new Promise(r => setTimeout(r, 300));
      await fetchTasks();
    } catch (error) {
      console.error('Error saving task:', error);
      setSaveError(tCommon('save_error'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteTask(id);
      fetchTasks();
    } catch (error) {
      console.error('Error deleting task:', error);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchTasks();
  };

  const editorContent = (
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
          autoFocus
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none"
          required
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('description_label')}</label>
        <textarea
          value={editDescription}
          onChange={e => setEditDescription(e.target.value)}
          rows={3}
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none resize-none"
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
          className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50 outline-none resize-none"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-1">{t('tags_label')}</label>
        <TagSelector tags={editTags} onChange={setEditTags} />
      </div>
    </div>
  );

  const tasksList = (
    <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
      {tasks.map(task => {
        const card = (
          <div
            className="p-4 bg-vault-900/60 rounded-lg border border-white/[0.06] cursor-pointer hover:border-white/[0.12] hover:bg-vault-900/80 transition-all"
            onClick={() => router.push(`/${locale}/tasks/${task.id}`)}
          >
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium text-text-primary truncate flex-1">{task.title}</h3>
              <button
                onClick={e => { e.stopPropagation(); handleDelete(task.id); }}
                className="hidden md:flex text-text-muted hover:text-red-400 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
            {task.description && (
              <p className="text-sm text-text-secondary mt-2 line-clamp-2">{task.description}</p>
            )}
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <span className={`px-2 py-0.5 text-xs rounded-full border ${statusColor(task.status)}`}>
                {t(`status_${task.status}` as any)}
              </span>
              <span className={`text-xs font-medium ${priorityColor(task.priority)}`}>
                {t(`priority_${task.priority}` as any)}
              </span>
              {task.alarm_at && !task.alarm_triggered && (
                <span className="text-xs text-amber-400 flex items-center gap-1">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                  </svg>
                  {new Date(task.alarm_at).toLocaleString(locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
              {task.alarm_at && task.alarm_triggered && (
                <span className="text-xs text-green-400 flex items-center gap-1">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  {t('alarm_triggered')}
                </span>
              )}
            </div>
            {task.due_date && (
              <p className="text-xs text-text-muted mt-2">
                {t('due_date_label')}: {new Date(task.due_date).toLocaleDateString(locale)}
              </p>
            )}
          </div>
        );

        return isMobile ? (
          <SwipeableRow
            key={task.id}
            onSwipeAction={() => handleDelete(task.id)}
            actionLabel={tCommon('delete')}
            actionColor="bg-red-600"
          >
            {card}
          </SwipeableRow>
        ) : (
          <div key={task.id}>{card}</div>
        );
      })}
    </div>
  );

  return (
    <div className="min-h-screen bg-vault-950">
      <div className="max-w-6xl mx-auto px-4 py-8 pb-20 md:pb-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
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
        ) : tasks.length === 0 ? (
          <p className="text-center text-text-muted py-12">{t('empty')}</p>
        ) : isMobile ? (
          <PullToRefresh onRefresh={fetchTasks}>
            {tasksList}
          </PullToRefresh>
        ) : (
          tasksList
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
      <FAB onClick={resetAndNewTask} label={t('new')} />

      {/* Editor — Mobile: MobileSheet */}
      {isMobile && (
        <MobileSheet
          open={showEditor}
          onClose={() => setShowEditor(false)}
          title={editingTask ? editingTask.title : t('new')}
          headerActions={
            editingTask ? (
              <button
                onClick={resetAndNewTask}
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
          <div className="bg-vault-900 border border-white/[0.08] rounded-xl shadow-2xl max-w-lg w-full p-6 max-h-[85vh] overflow-y-auto">
            <h2 className="text-xl font-bold text-text-primary font-display mb-4">
              {editingTask ? editingTask.title : t('new')}
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
