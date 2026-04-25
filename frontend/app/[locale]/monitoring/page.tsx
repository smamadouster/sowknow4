'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';

interface HealthData {
  status: string;
  database: string;
  redis: string;
  vault: string;
  nats: string;
  ollama: string;
  checked_at: string;
}

interface CeleryData {
  status: string;
  workers: number;
  active_tasks: number;
  reserved_tasks: number;
  worker_names: string[];
}

interface ServiceStatus {
  name: string;
  status: string;
  type: 'infrastructure' | 'application' | 'external';
}

const STATUS_COLORS: Record<string, string> = {
  ok: 'bg-green-500',
  healthy: 'bg-green-500',
  error: 'bg-red-500',
  degraded: 'bg-yellow-500',
  unavailable: 'bg-gray-400',
  unknown: 'bg-gray-400',
};

const STATUS_TEXT_COLORS: Record<string, string> = {
  ok: 'text-green-700 bg-green-50 border-green-200',
  healthy: 'text-green-700 bg-green-50 border-green-200',
  error: 'text-red-700 bg-red-50 border-red-200',
  degraded: 'text-yellow-700 bg-yellow-50 border-yellow-200',
  unavailable: 'text-gray-500 bg-gray-50 border-gray-200',
  unknown: 'text-gray-500 bg-gray-50 border-gray-200',
};

export default function MonitoringPage() {
  const t = useTranslations('monitoring');
  const [health, setHealth] = useState<HealthData | null>(null);
  const [celery, setCelery] = useState<CeleryData | null>(null);
  const [celeryError, setCeleryError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchHealth = useCallback(async () => {
    try {
      const [healthRes, celeryRes] = await Promise.allSettled([
        fetch('/api/v1/health', { credentials: 'include' }),
        fetch('/api/v1/health/celery', { credentials: 'include' }),
      ]);

      if (healthRes.status === 'fulfilled' && healthRes.value.ok) {
        setHealth(await healthRes.value.json());
      } else if (healthRes.status === 'fulfilled') {
        // 503 still has a valid JSON body
        try { setHealth(await healthRes.value.json()); } catch {}
      }

      if (celeryRes.status === 'fulfilled' && celeryRes.value.ok) {
        setCelery(await celeryRes.value.json());
        setCeleryError(null);
      } else if (celeryRes.status === 'fulfilled') {
        try {
          const err = await celeryRes.value.json();
          setCeleryError(err.detail || 'Celery unavailable');
        } catch {
          setCeleryError('Celery unavailable');
        }
        setCelery(null);
      }

      setLastRefresh(new Date());
    } catch (e) {
      console.error('Health fetch failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchHealth]);

  const services: ServiceStatus[] = health
    ? [
        { name: 'PostgreSQL', status: health.database, type: 'infrastructure' },
        { name: 'Redis', status: health.redis, type: 'infrastructure' },
        { name: 'Vault', status: health.vault, type: 'infrastructure' },
        { name: 'NATS', status: health.nats, type: 'infrastructure' },
        { name: 'Backend API', status: health.status === 'error' ? 'error' : 'ok', type: 'application' },
        { name: 'Celery Worker', status: celery ? 'ok' : 'error', type: 'application' },
        { name: 'Ollama (Local LLM)', status: health.ollama, type: 'external' },
      ]
    : [];

  const healthyCount = services.filter((s) => s.status === 'ok' || s.status === 'healthy').length;
  const totalCount = services.length;
  const overallStatus = !health
    ? 'unknown'
    : health.status === 'ok'
      ? 'ok'
      : health.status === 'degraded'
        ? 'degraded'
        : 'error';

  const overallLabel =
    overallStatus === 'ok'
      ? t('all_healthy')
      : overallStatus === 'degraded'
        ? t('degraded')
        : overallStatus === 'error'
          ? t('critical')
          : t('loading');

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-sm text-gray-500 mt-1">{t('subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-gray-500">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-300"
            />
            {t('auto_refresh')}
          </label>
          <button
            onClick={() => { setLoading(true); fetchHealth(); }}
            className="px-3 py-1.5 text-sm font-medium bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
          >
            {t('refresh')}
          </button>
        </div>
      </div>

      {/* Overall status banner */}
      <div
        className={`rounded-xl p-5 border ${
          overallStatus === 'ok'
            ? 'bg-green-50 border-green-200'
            : overallStatus === 'degraded'
              ? 'bg-yellow-50 border-yellow-200'
              : overallStatus === 'error'
                ? 'bg-red-50 border-red-200'
                : 'bg-gray-50 border-gray-200'
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div className="flex items-center gap-3">
            <div
              className={`w-4 h-4 rounded-full ${STATUS_COLORS[overallStatus] || 'bg-gray-400'} ${
                overallStatus === 'ok' ? 'animate-pulse' : ''
              }`}
            />
            <div>
              <p className="text-lg font-semibold text-gray-900">{overallLabel}</p>
              <p className="text-sm text-gray-500">
                {totalCount > 0
                  ? t('services_healthy', { healthy: healthyCount, total: totalCount })
                  : ''}
              </p>
            </div>
          </div>
          {lastRefresh && (
            <p className="text-xs text-gray-400">
              {t('last_check')}: {lastRefresh.toLocaleTimeString()}
            </p>
          )}
        </div>
      </div>

      {loading && !health ? (
        <div className="text-center py-12 text-gray-400">{t('loading')}</div>
      ) : (
        <>
          {/* Service grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {services.map((svc) => (
              <div
                key={svc.name}
                className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm"
              >
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold text-gray-800">{svc.name}</h3>
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${
                      STATUS_TEXT_COLORS[svc.status] || STATUS_TEXT_COLORS['unknown']
                    }`}
                  >
                    {svc.status}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <div
                    className={`w-2.5 h-2.5 rounded-full ${STATUS_COLORS[svc.status] || 'bg-gray-400'}`}
                  />
                  <span className="text-xs text-gray-400 capitalize">{svc.type}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Celery details panel */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-800">{t('celery_title')}</h2>
            </div>
            <div className="p-5">
              {celery ? (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div className="text-center">
                    <p className="text-3xl font-bold text-green-600">{celery.workers}</p>
                    <p className="text-xs text-gray-500 mt-1">{t('workers')}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-3xl font-bold text-blue-600">{celery.active_tasks}</p>
                    <p className="text-xs text-gray-500 mt-1">{t('active_tasks')}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-3xl font-bold text-yellow-600">{celery.reserved_tasks}</p>
                    <p className="text-xs text-gray-500 mt-1">{t('reserved_tasks')}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-mono text-gray-600 truncate">
                      {celery.worker_names?.[0] || '-'}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">{t('worker_name')}</p>
                  </div>
                </div>
              ) : (
                <div className="text-center py-4">
                  <p className="text-sm text-red-500">
                    {celeryError || t('celery_unavailable')}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Architecture info */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-800">{t('architecture_title')}</h2>
            </div>
            <div className="p-5 text-sm text-gray-600 space-y-2">
              <p><span className="font-medium text-gray-800">{t('layer_1')}</span> {t('layer_1_desc')}</p>
              <p><span className="font-medium text-gray-800">{t('layer_2')}</span> {t('layer_2_desc')}</p>
              <p><span className="font-medium text-gray-800">{t('layer_3')}</span> {t('layer_3_desc')}</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
