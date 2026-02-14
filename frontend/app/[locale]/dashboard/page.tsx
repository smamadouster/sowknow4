'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';

interface Stats {
  total_documents: number;
  uploads_today: number;
  indexed_pages: number;
  public_documents: number;
  confidential_documents: number;
  total_users: number;
  active_users_today: number;
}

interface QueueStats {
  pending: number;
  in_progress: number;
  failed: number;
  total: number;
}

interface Anomaly {
  id: string;
  document_id: string;
  filename: string;
  status: string;
  error_message: string;
  hours_stuck: number;
  created_at: string;
  updated_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export default function DashboardPage() {
  const t = useTranslations('dashboard');
  const tAdmin = useTranslations('admin');
  const tCommon = useTranslations('common');
  
  const [stats, setStats] = useState<Stats | null>(null);
  const [queueStats, setQueueStats] = useState<QueueStats | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  useEffect(() => {
    loadDashboard();
    const interval = setInterval(loadDashboard, 60000);
    return () => clearInterval(interval);
  }, []);

  const getToken = (): string | null => {
    if (typeof window === 'undefined') return null;
    const match = document.cookie.match(/access_token=([^;]+)/);
    return match ? match[1] : null;
  };

  const loadDashboard = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const token = getToken();
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      
      const [statsRes, queueRes, anomaliesRes] = await Promise.all([
        fetch(`${API_BASE}/v1/admin/stats`, { credentials: 'include', headers }),
        fetch(`${API_BASE}/v1/admin/queue-stats`, { credentials: 'include', headers }),
        fetch(`${API_BASE}/v1/admin/anomalies`, { credentials: 'include', headers }),
      ]);

      if (statsRes.ok) {
        const data = await statsRes.json();
        setStats(data);
      }
      
      if (queueRes.ok) {
        const data = await queueRes.json();
        setQueueStats(data);
      }
      
      if (anomaliesRes.ok) {
        const data = await anomaliesRes.json();
        setAnomalies(data.anomalies || data || []);
      }
      
      setLastUpdated(new Date());
    } catch (e) {
      console.error('Error loading dashboard:', e);
      setError(tCommon('error'));
    } finally {
      setLoading(false);
    }
  };

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
              <p className="text-3xl font-bold text-gray-900">{stats?.indexed_pages ?? '-'}</p>
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
              <p className="text-3xl font-bold text-gray-900">{queueStats?.total ?? '-'}</p>
            </div>
            <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </div>
          </div>
          <div className="mt-4 flex gap-4 text-sm">
            <span className="text-yellow-600">{queueStats?.pending ?? 0} pending</span>
            <span className="text-blue-600">{queueStats?.in_progress ?? 0} processing</span>
            <span className="text-red-600">{queueStats?.failed ?? 0} failed</span>
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
              width: queueStats && queueStats.total > 0 
                ? `${((queueStats.in_progress / queueStats.total) * 100)}%` 
                : '0%' 
            }}
          ></div>
        </div>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-yellow-600">{queueStats?.pending ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('pending_tasks')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-blue-600">{queueStats?.in_progress ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('in_progress_tasks')}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-red-600">{queueStats?.failed ?? 0}</p>
            <p className="text-sm text-gray-500">{tAdmin('failed_tasks')}</p>
          </div>
        </div>
      </div>

      {/* Anomalies Report */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">
            {tAdmin('anomalies_title')}
          </h2>
          <button
            onClick={loadDashboard}
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
                    <tr key={anomaly.id} className="border-b border-gray-100 hover:bg-gray-50">
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
                          {tAdmin('hours_stuck', { hours: anomaly.hours_stuck })}
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
