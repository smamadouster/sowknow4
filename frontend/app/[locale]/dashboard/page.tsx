'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from 'next/navigation';
import {
  PieChart, Pie, Cell, Tooltip as ReTooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, LabelList,
  AreaChart, Area,
} from 'recharts';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

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

interface ArticlesStats {
  total_articles: number;
  indexed_articles: number;
  pending_articles: number;
  generating_articles: number;
  error_articles: number;
}

interface ArticlesPoint {
  day: string;
  count: number;
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
  health: 'green' | 'yellow' | 'red';
}

interface PipelineStats {
  stages: PipelineStageData[];
  total_active: number;
  bottleneck_stage: string | null;
  overall_health: 'green' | 'yellow' | 'red';
}

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
  const router = useRouter();
  const locale = useLocale();
  const { user, _hasHydrated } = useAuthStore();

  const [stats, setStats] = useState<Stats | null>(null);
  const [articlesStats, setArticlesStats] = useState<ArticlesStats | null>(null);
  const [articlesHistory, setArticlesHistory] = useState<ArticlesPoint[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [uploadsHistory, setUploadsHistory] = useState<UploadsPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [pipelineStats, setPipelineStats] = useState<PipelineStats | null>(null);
  const [lastPipelineUpdate, setLastPipelineUpdate] = useState<Date>(new Date());

  // Role guard: redirect non-admins
  useEffect(() => {
    if (!_hasHydrated) return;
    if (!user || (user.role !== 'admin' && user.role !== 'superuser')) {
      router.replace(`/${locale}`);
    }
  }, [_hasHydrated, user, locale, router]);

  const loadSlowStats = async () => {
    try {
      const [statsRes, anomaliesRes, historyRes, articlesHistoryRes] = await Promise.all([
        api.getStats(),
        api.getAnomalies(),
        api.getUploadsHistory(),
        api.getArticlesHistory(),
      ]);

      let anyError = false;

      if (statsRes.data) {
        setStats(statsRes.data as Stats);
      } else {
        anyError = true;
        console.error('Stats error:', statsRes.error);
      }

      if (anomaliesRes.data) {
        const data = anomaliesRes.data as { anomalies?: Anomaly[] };
        setAnomalies(data.anomalies || []);
      } else {
        console.error('Anomalies error:', anomaliesRes.error);
      }

      if (historyRes.data) {
        const data = historyRes.data as { history?: UploadsPoint[] };
        setUploadsHistory(data.history || []);
      } else {
        console.error('Uploads history error:', historyRes.error);
      }

      if (articlesHistoryRes.data) {
        const data = articlesHistoryRes.data as { history?: ArticlesPoint[] };
        setArticlesHistory(data.history || []);
      } else {
        console.error('Articles history error:', articlesHistoryRes.error);
      }

      if (anyError) {
        setError(tCommon('error'));
      }
      setLastUpdated(new Date());
    } catch (e) {
      console.error('Error loading slow stats:', e);
      setError(tCommon('error'));
    }
  };

  const loadLiveStats = async () => {
    try {
      const [articlesRes, pipelineRes] = await Promise.all([
        api.getArticlesStats(),
        api.getPipelineStats(),
      ]);

      if (articlesRes.data) {
        setArticlesStats(articlesRes.data as ArticlesStats);
      } else {
        console.error('Articles stats error:', articlesRes.error);
      }

      if (pipelineRes.data) {
        setPipelineStats(pipelineRes.data as PipelineStats);
      } else {
        console.error('Pipeline stats error:', pipelineRes.error);
      }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!_hasHydrated || loading) {
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
    <div className="p-4 sm:p-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-6">
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
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6">
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
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            <span className="text-green-600">{stats?.public_documents ?? 0} public</span>
            <span className="text-orange-600">{stats?.confidential_documents ?? 0} confidential</span>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6">
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

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6">
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

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">{t('total_articles')}</p>
              <p className="text-3xl font-bold text-gray-900">{articlesStats?.total_articles ?? '-'}</p>
            </div>
            <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            <span className="text-green-600">{articlesStats?.indexed_articles ?? 0} indexed</span>
            <span className="text-blue-600">{articlesStats?.generating_articles ?? 0} generating</span>
            <span className="text-red-600">{articlesStats?.error_articles ?? 0} error</span>
          </div>
        </div>
      </div>

      {/* Articles Status */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6 mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('articles_status')}</h2>
        <div className="w-full bg-gray-200 rounded-full h-4 mb-4">
          <div
            className="bg-blue-600 h-4 rounded-full transition-all"
            style={{
              width: articlesStats && articlesStats.total_articles > 0
                ? `${((articlesStats.indexed_articles / articlesStats.total_articles) * 100)}%`
                : '0%'
            }}
          ></div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-green-600">{articlesStats?.indexed_articles ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('indexed_articles')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-yellow-600">{articlesStats?.pending_articles ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('pending_articles')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-blue-600">{articlesStats?.generating_articles ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('generating_articles')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-red-600">{articlesStats?.error_articles ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('error_articles')}</p>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Document Type Distribution */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6">
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
            <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
              {tCommon('error')}
            </div>
          )}
        </div>

        {/* Articles Breakdown */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('articles_breakdown')}</h2>
          {articlesStats ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4 text-center">
                <div className="bg-green-50 rounded-lg p-2">
                  <p className="text-lg font-bold text-green-700">{articlesStats.indexed_articles.toLocaleString()}</p>
                  <p className="text-xs text-green-600">{tAdmin('indexed_articles')}</p>
                </div>
                <div className="bg-yellow-50 rounded-lg p-2">
                  <p className="text-lg font-bold text-yellow-700">{articlesStats.pending_articles.toLocaleString()}</p>
                  <p className="text-xs text-yellow-600">{tAdmin('pending_articles')}</p>
                </div>
                <div className="bg-blue-50 rounded-lg p-2">
                  <p className="text-lg font-bold text-blue-700">{articlesStats.generating_articles.toLocaleString()}</p>
                  <p className="text-xs text-blue-600">{tAdmin('generating_articles')}</p>
                </div>
                <div className="bg-red-50 rounded-lg p-2">
                  <p className="text-lg font-bold text-red-700">{articlesStats.error_articles.toLocaleString()}</p>
                  <p className="text-xs text-red-600">{tAdmin('error_articles')}</p>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={[
                    { name: tAdmin('indexed_articles'), value: articlesStats.indexed_articles, fill: '#22c55e' },
                    { name: tAdmin('pending_articles'), value: articlesStats.pending_articles, fill: '#eab308' },
                    { name: tAdmin('generating_articles'), value: articlesStats.generating_articles, fill: '#3b82f6' },
                    { name: tAdmin('error_articles'), value: articlesStats.error_articles, fill: '#ef4444' },
                  ]}
                  margin={{ top: 20, right: 16, left: 0, bottom: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#374151' }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#374151' }} />
                  <ReTooltip />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {[
                      <Cell key="indexed" fill="#22c55e" />,
                      <Cell key="pending" fill="#eab308" />,
                      <Cell key="generating" fill="#3b82f6" />,
                      <Cell key="error" fill="#ef4444" />,
                    ]}
                    <LabelList dataKey="value" position="top" fill="#111827" fontSize={13} fontWeight={700} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </>
          ) : (
            <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
              {tCommon('error')}
            </div>
          )}
        </div>
      </div>

      {/* Uploads Trend */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6 mb-8">
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
          <div className="h-56 flex items-center justify-center text-gray-400 text-sm">
            {tCommon('error')}
          </div>
        )}
      </div>

      {/* Articles Trend */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6 mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('articles_trend')}</h2>
        {articlesHistory.length > 0 ? (
          <>
            <div className="flex flex-wrap gap-3 mb-4">
              {articlesHistory.map((pt) => (
                <div key={pt.day} className="bg-violet-50 rounded-lg px-3 py-2 text-center min-w-[80px]">
                  <p className="text-sm font-bold text-violet-800">{pt.count.toLocaleString()}</p>
                  <p className="text-xs text-violet-600">{pt.day.slice(5)}</p>
                </div>
              ))}
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={articlesHistory} margin={{ top: 20, right: 16, left: 0, bottom: 8 }}>
                <defs>
                  <linearGradient id="articlesGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6D28D9" stopOpacity={0.95} />
                    <stop offset="95%" stopColor="#6D28D9" stopOpacity={0.35} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#374151' }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#374151' }} />
                <ReTooltip />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#4C1D95"
                  strokeWidth={3}
                  fill="url(#articlesGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </>
        ) : (
          <div className="h-56 flex items-center justify-center text-gray-400 text-sm">
            {tCommon('error')}
          </div>
        )}
      </div>

      {/* Pipeline Health */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 sm:p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-900">Pipeline Health</h2>
            {pipelineStats && (
              <span
                className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-semibold ${
                  (pipelineStats.overall_health || 'green') === 'green'
                    ? 'bg-green-100 text-green-800'
                    : (pipelineStats.overall_health || 'green') === 'yellow'
                    ? 'bg-yellow-100 text-yellow-800'
                    : 'bg-red-100 text-red-800'
                }`}
              >
                {(pipelineStats.overall_health || 'green') === 'green' && (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                )}
                {(pipelineStats.overall_health || 'green') === 'yellow' && (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                )}
                {(pipelineStats.overall_health || 'green') === 'red' && (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                )}
                {(pipelineStats.overall_health || 'green') === 'green'
                  ? 'Healthy'
                  : (pipelineStats.overall_health || 'green') === 'yellow'
                  ? 'Congested'
                  : 'Blocked'}
              </span>
            )}
          </div>
          <div className="text-xs text-gray-400">
            Updated {lastPipelineUpdate.toLocaleTimeString()}
          </div>
        </div>

        {pipelineStats ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b-2 border-gray-200">
                  <th className="text-left py-2.5 pr-4 font-semibold text-gray-600 w-28">Stage</th>
                  <th className="text-left py-2.5 pr-4 font-semibold text-gray-600 w-40">Status</th>
                  <th className="text-right py-2.5 px-3 font-semibold text-gray-600 w-24">Pending</th>
                  <th className="text-right py-2.5 px-3 font-semibold text-gray-600 w-24">Running</th>
                  <th className="text-right py-2.5 px-3 font-semibold text-gray-600 w-20">Failed</th>
                  <th className="text-right py-2.5 pl-3 font-semibold text-gray-600 w-28">Throughput</th>
                </tr>
              </thead>
              <tbody>
                {pipelineStats.stages.map((stage) => {
                  const health = stage.health || 'green';
                  const rowBg =
                    health === 'red'
                      ? 'bg-red-50/60'
                      : health === 'yellow'
                      ? 'bg-yellow-50/40'
                      : '';
                  const leftBorder =
                    health === 'red'
                      ? 'border-l-4 border-l-red-400'
                      : health === 'yellow'
                      ? 'border-l-4 border-l-yellow-400'
                      : 'border-l-4 border-l-green-400';

                  const statusIcon =
                    health === 'green' ? (
                      <span className="inline-flex items-center gap-2 text-green-700 font-medium">
                        <span>🟢</span>
                        OK
                      </span>
                    ) : health === 'yellow' ? (
                      <span className="inline-flex items-center gap-2 text-yellow-700 font-medium">
                        <span>🟡</span>
                        Backlog
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-2 text-red-700 font-medium">
                        <span>🔴</span>
                        Needs Attention
                      </span>
                    );

                  return (
                    <tr
                      key={stage.stage}
                      className={`border-b border-gray-100 ${rowBg} ${leftBorder}`}
                    >
                      <td className="py-3 pr-4 font-semibold text-gray-800">
                        {STAGE_LABELS[stage.stage] ?? stage.stage}
                      </td>
                      <td className="py-3 pr-4">{statusIcon}</td>
                      <td className="py-3 px-3 text-right font-mono text-gray-700">
                        {stage.pending.toLocaleString()}
                      </td>
                      <td className="py-3 px-3 text-right font-mono text-gray-700">
                        {stage.running.toLocaleString()}
                      </td>
                      <td className="py-3 px-3 text-right font-mono">
                        {stage.failed > 0 ? (
                          <span className="text-red-600 font-semibold">{stage.failed}</span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="py-3 pl-3 text-right font-mono text-gray-700">
                        {stage.throughput_per_hour}/hr
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="h-60 flex items-center justify-center text-gray-400 text-sm">
            {tCommon('error')}
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
