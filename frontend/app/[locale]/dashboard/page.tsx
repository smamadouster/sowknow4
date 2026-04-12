'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import {
  PieChart, Pie, Cell, Tooltip as ReTooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  AreaChart, Area,
} from 'recharts';

interface Stats {
  total_documents: number;
  uploads_today: number;
  indexed_documents: number;
  public_documents: number;
  confidential_documents: number;
  total_users: number;
  active_sessions: number;
  processing_documents: number;
  error_documents: number;
}

interface QueueStats {
  pending_tasks: number;
  in_progress_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  average_wait_time: number | null;
  longest_running_task: string | null;
}

interface UploadsPoint {
  day: string;
  count: number;
}

interface Anomaly {
  document_id: string;
  filename: string;
  bucket: string;
  status: string;
  error_message: string | null;
  stuck_duration_hours: number;
  created_at: string;
  last_task_type: string | null;
}

interface PipelineStageData {
  stage: string;
  pending: number;
  running: number;
  failed: number;
  throughput_per_hour: number;
  throughput_per_10min: number;
}

interface PipelineStats {
  stages: PipelineStageData[];
  total_active: number;
  bottleneck_stage: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

const STAGE_LABELS: Record<string, string> = {
  uploaded: 'Uploaded',
  ocr: 'OCR',
  chunked: 'Chunking',
  embedded: 'Embedding',
  indexed: 'Indexing',
  articles: 'Articles',
  entities: 'Entities',
  enriched: 'Enriched',
};

export default function DashboardPage() {
  const t = useTranslations('dashboard');
  const tAdmin = useTranslations('admin');
  const tCommon = useTranslations('common');

  const [stats, setStats] = useState<Stats | null>(null);
  const [queueStats, setQueueStats] = useState<QueueStats | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [uploadsHistory, setUploadsHistory] = useState<UploadsPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [pipelineStats, setPipelineStats] = useState<PipelineStats | null>(null);
  const [lastPipelineUpdate, setLastPipelineUpdate] = useState<Date>(new Date());

  const loadSlowStats = async () => {
    try {
      const [statsRes, anomaliesRes, historyRes] = await Promise.all([
        fetch(`${API_BASE}/v1/admin/stats`, { credentials: 'include' }),
        fetch(`${API_BASE}/v1/admin/anomalies`, { credentials: 'include' }),
        fetch(`${API_BASE}/v1/admin/uploads-history`, { credentials: 'include' }),
      ]);

      if (statsRes.ok) setStats(await statsRes.json());
      if (anomaliesRes.ok) {
        const data = await anomaliesRes.json();
        setAnomalies(data.anomalies || data || []);
      }
      if (historyRes.ok) {
        const data = await historyRes.json();
        setUploadsHistory(data.history || []);
      }
      setLastUpdated(new Date());
    } catch (e) {
      console.error('Error loading slow stats:', e);
      setError(tCommon('error'));
    }
  };

  const loadLiveStats = async () => {
    try {
      const [queueRes, pipelineRes] = await Promise.all([
        fetch(`${API_BASE}/v1/admin/queue-stats`, { credentials: 'include' }),
        fetch(`${API_BASE}/v1/admin/pipeline-stats`, { credentials: 'include' }),
      ]);

      if (queueRes.ok) setQueueStats(await queueRes.json());
      if (pipelineRes.ok) setPipelineStats(await pipelineRes.json());
      setLastPipelineUpdate(new Date());
    } catch (e) {
      console.error('Error loading live stats:', e);
    }
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([loadSlowStats(), loadLiveStats()]).finally(() => setLoading(false));

    const slowInterval = setInterval(loadSlowStats, 60_000);
    const liveInterval = setInterval(loadLiveStats, 10_000);
    return () => {
      clearInterval(slowInterval);
      clearInterval(liveInterval);
    };
  }, []);

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">{tCommon('loading')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{t('title')}</h1>
        <div className="text-sm text-gray-500">
          Last updated: {lastUpdated.toLocaleTimeString()}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-3 rounded-lg mb-6">
          {error}
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">{t('total_documents')}</p>
              <p className="text-3xl font-bold text-gray-900">{stats?.total_documents ?? '-'}</p>
            </div>
            <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
          </div>
          <div className="mt-4 flex gap-4 text-sm">
            <span className="text-green-600">{stats?.public_documents ?? 0} public</span>
            <span className="text-orange-600">{stats?.confidential_documents ?? 0} confidential</span>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">{t('uploads_today')}</p>
              <p className="text-3xl font-bold text-gray-900">{stats?.uploads_today ?? '-'}</p>
            </div>
            <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">{t('indexed_pages')}</p>
              <p className="text-3xl font-bold text-gray-900">{stats?.indexed_documents ?? '-'}</p>
            </div>
            <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">{t('processing_queue')}</p>
              <p className="text-3xl font-bold text-gray-900">{queueStats ? queueStats.pending_tasks + queueStats.in_progress_tasks + queueStats.failed_tasks : '-'}</p>
            </div>
            <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </div>
          </div>
          <div className="mt-4 flex gap-4 text-sm">
            <span className="text-yellow-600">{queueStats?.pending_tasks ?? 0} pending</span>
            <span className="text-blue-600">{queueStats?.in_progress_tasks ?? 0} processing</span>
            <span className="text-red-600">{queueStats?.failed_tasks ?? 0} failed</span>
          </div>
        </div>
      </div>

      {/* Queue Status */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('processing_queue')}</h2>
        <div className="w-full bg-gray-200 rounded-full h-4 mb-4">
          <div
            className="bg-blue-600 h-4 rounded-full transition-all"
            style={{
              width: queueStats && (queueStats.pending_tasks + queueStats.in_progress_tasks + queueStats.failed_tasks) > 0
                ? `${((queueStats.in_progress_tasks / (queueStats.pending_tasks + queueStats.in_progress_tasks + queueStats.failed_tasks)) * 100)}%`
                : '0%'
            }}
          ></div>
        </div>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-yellow-600">{queueStats?.pending_tasks ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('pending_tasks')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-blue-600">{queueStats?.in_progress_tasks ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('in_progress_tasks')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-red-600">{queueStats?.failed_tasks ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('failed_tasks')}</p>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Document Type Distribution */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('document_distribution')}</h2>
          {stats ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={[
                    { name: t('public'), value: stats.public_documents },
                    { name: t('confidential'), value: stats.confidential_documents },
                  ]}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={3}
                  dataKey="value"
                  label={({ name, percent }) => `${name} ${Math.round(percent * 100)}%`}
                  labelLine={false}
                >
                  <Cell fill="#22c55e" />
                  <Cell fill="#f97316" />
                </Pie>
                <ReTooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center">
              <div className="animate-pulse bg-gray-200 rounded-full w-40 h-40" />
            </div>
          )}
        </div>

        {/* Queue Status Breakdown */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('queue_breakdown')}</h2>
          {queueStats ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart
                data={[
                  { name: tAdmin('pending_tasks'), value: queueStats.pending_tasks, fill: '#eab308' },
                  { name: tAdmin('in_progress_tasks'), value: queueStats.in_progress_tasks, fill: '#3b82f6' },
                  { name: tAdmin('failed_tasks'), value: queueStats.failed_tasks, fill: '#ef4444' },
                ]}
                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <ReTooltip />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {[
                    <Cell key="pending" fill="#eab308" />,
                    <Cell key="in_progress" fill="#3b82f6" />,
                    <Cell key="failed" fill="#ef4444" />,
                  ]}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center gap-4">
              {[1, 2, 3].map(i => (
                <div key={i} className="animate-pulse bg-gray-200 rounded w-16" style={{ height: `${i * 40}px` }} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Uploads Trend */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('uploads_trend')}</h2>
        {uploadsHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={uploadsHistory} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <defs>
                <linearGradient id="uploadsGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#FFEB3B" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#FFEB3B" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <ReTooltip />
              <Area
                type="monotone"
                dataKey="count"
                stroke="#F59E0B"
                strokeWidth={2}
                fill="url(#uploadsGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-56 flex items-center justify-center">
            <div className="animate-pulse bg-gray-200 rounded w-full h-full" />
          </div>
        )}
      </div>

      {/* Pipeline Funnel */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-900">Pipeline</h2>
            {pipelineStats && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                {pipelineStats.total_active} active
              </span>
            )}
          </div>
          <div className="text-xs text-gray-400">
            Updated {lastPipelineUpdate.toLocaleTimeString()}
          </div>
        </div>

        {pipelineStats ? (
          <div className="space-y-3">
            {(() => {
              const maxPending = Math.max(...pipelineStats.stages.map(s => s.pending), 1);
              return pipelineStats.stages.map((stage) => {
                const isBottleneck = stage.stage === pipelineStats.bottleneck_stage;
                const barWidth = Math.round((stage.pending / maxPending) * 100);

                return (
                  <div
                    key={stage.stage}
                    className={`flex items-center gap-4 p-3 rounded-lg ${isBottleneck ? 'bg-amber-50 border border-amber-200' : 'bg-gray-50'}`}
                  >
                    {/* Stage label */}
                    <div className="w-24 shrink-0">
                      <span className="text-sm font-medium text-gray-700">
                        {STAGE_LABELS[stage.stage] ?? stage.stage}
                      </span>
                      {isBottleneck && (
                        <span className="ml-1 text-xs text-amber-600">⚡</span>
                      )}
                    </div>

                    {/* Pending bar */}
                    <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-all ${isBottleneck ? 'bg-amber-400' : 'bg-blue-400'}`}
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>

                    {/* Counts */}
                    <div className="flex items-center gap-3 text-xs shrink-0">
                      <span className="text-yellow-700 font-medium w-16 text-right">
                        {stage.pending.toLocaleString()} pending
                      </span>
                      <span className="text-blue-700 w-16 text-right">
                        {stage.running} running
                      </span>
                      {stage.failed > 0 && (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                          {stage.failed} failed
                        </span>
                      )}
                      <span className="text-gray-400 w-28 text-right">
                        {stage.throughput_per_hour}/hr · {stage.throughput_per_10min}/10min
                      </span>
                    </div>
                  </div>
                );
              });
            })()}
          </div>
        ) : (
          <div className="space-y-2">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-10 bg-gray-100 rounded-lg animate-pulse" />
            ))}
          </div>
        )}
      </div>

      {/* Anomalies Report */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">
            {tAdmin('anomalies_title')}
          </h2>
          <button
            onClick={() => { loadSlowStats().catch(console.error); loadLiveStats().catch(console.error); }}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </button>
        </div>

        {anomalies.length === 0 ? (
          <div className="text-center py-8">
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-gray-600">{t('no_anomalies')}</p>
            <p className="text-sm text-gray-400 mt-1">All documents processing normally</p>
          </div>
        ) : (
          <div>
            <p className="text-sm text-red-600 mb-4">
              {t('anomalies_found', { count: anomalies.length })}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-3 px-4 text-sm font-medium text-gray-500">Document</th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-gray-500">Status</th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-gray-500">Stuck Time</th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-gray-500">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {anomalies.map((anomaly) => (
                    <tr key={anomaly.document_id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-3 px-4">
                        <p className="font-medium text-gray-900">{anomaly.filename}</p>
                        <p className="text-xs text-gray-400">{anomaly.document_id}</p>
                      </td>
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                          {anomaly.status}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span className="text-red-600 font-medium">
                          {tAdmin('hours_stuck', { hours: anomaly.stuck_duration_hours })}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <p className="text-sm text-gray-600 max-w-xs truncate">{anomaly.error_message}</p>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
