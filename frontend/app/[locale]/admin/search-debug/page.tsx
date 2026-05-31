'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { api } from '@/lib/api';

interface DebugResult {
  document_id: string;
  document_name: string;
  chunk_text: string;
  final_score: number;
  match_source: string;
  result_type: string;
}

interface VariantResult {
  results: DebugResult[];
  elapsed_ms: number;
  source_counts: Record<string, number>;
}

interface DebugResponse {
  variant_a: VariantResult;
  variant_b: VariantResult;
  common_ids: string[];
  only_in_a: string[];
  only_in_b: string[];
}

const DEFAULT_VARIANT_A = {
  semantic_weight: 0.7,
  keyword_weight: 0.3,
  regconfig: 'simple',
  rerank: true,
  limit: 20,
};

const DEFAULT_VARIANT_B = {
  semantic_weight: 0.4,
  keyword_weight: 0.6,
  regconfig: 'french',
  rerank: true,
  limit: 20,
};

export default function SearchDebugPage() {
  const t = useTranslations('admin');
  const [query, setQuery] = useState('');
  const [variantA, setVariantA] = useState(DEFAULT_VARIANT_A);
  const [variantB, setVariantB] = useState(DEFAULT_VARIANT_B);
  const [result, setResult] = useState<DebugResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runDebug = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.post<DebugResponse>('/admin/search-debug', {
        query,
        variant_a: variantA,
        variant_b: variantB,
      });
      setResult(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  const commonSet = new Set(result?.common_ids || []);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-text-primary mb-6">🔬 {t('search_debug') || 'Search Debug'}</h1>

      <div className="bg-vault-900/60 border border-white/[0.06] rounded-lg p-4 mb-6">
        <label className="block text-sm font-medium text-text-secondary mb-2">Query</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runDebug()}
            placeholder="Enter search query..."
            className="flex-1 bg-vault-800 border border-white/10 rounded px-3 py-2 text-text-primary placeholder:text-text-muted/40 focus:outline-none focus:border-amber-400/50"
          />
          <button
            onClick={runDebug}
            disabled={loading || !query.trim()}
            className="bg-amber-500/20 text-amber-400 border border-amber-400/30 rounded px-4 py-2 font-medium hover:bg-amber-500/30 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Running…' : 'Run A/B'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-rose-500/10 border border-rose-400/20 rounded-lg p-4 mb-6 text-rose-400 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <VariantConfig title="Variant A" config={variantA} onChange={setVariantA} />
        <VariantConfig title="Variant B" config={variantB} onChange={setVariantB} />
      </div>

      {result && (
        <>
          <div className="grid grid-cols-3 gap-4 mb-6">
            <DiffCard label="Common" count={result.common_ids.length} color="text-emerald-400" bg="bg-emerald-500/10" />
            <DiffCard label="Only in A" count={result.only_in_a.length} color="text-amber-400" bg="bg-amber-500/10" />
            <DiffCard label="Only in B" count={result.only_in_b.length} color="text-blue-400" bg="bg-blue-500/10" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <VariantResults title="Variant A" data={result.variant_a} commonSet={commonSet} highlight="amber" />
            <VariantResults title="Variant B" data={result.variant_b} commonSet={commonSet} highlight="blue" />
          </div>
        </>
      )}
    </div>
  );
}

function VariantConfig({ title, config, onChange }: { title: string; config: typeof DEFAULT_VARIANT_A; onChange: (c: typeof DEFAULT_VARIANT_A) => void }) {
  const update = (key: string, value: any) => onChange({ ...config, [key]: value });
  return (
    <div className="bg-vault-900/60 border border-white/[0.06] rounded-lg p-4">
      <h3 className="text-sm font-semibold text-text-primary mb-3">{title}</h3>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-xs text-text-secondary">
          Semantic Weight
          <input type="number" step={0.1} min={0} max={1} value={config.semantic_weight} onChange={(e) => update('semantic_weight', parseFloat(e.target.value))} className="w-full mt-1 bg-vault-800 border border-white/10 rounded px-2 py-1 text-text-primary text-sm" />
        </label>
        <label className="text-xs text-text-secondary">
          Keyword Weight
          <input type="number" step={0.1} min={0} max={1} value={config.keyword_weight} onChange={(e) => update('keyword_weight', parseFloat(e.target.value))} className="w-full mt-1 bg-vault-800 border border-white/10 rounded px-2 py-1 text-text-primary text-sm" />
        </label>
        <label className="text-xs text-text-secondary">
          Regconfig
          <select value={config.regconfig} onChange={(e) => update('regconfig', e.target.value)} className="w-full mt-1 bg-vault-800 border border-white/10 rounded px-2 py-1 text-text-primary text-sm">
            <option value="simple">simple</option>
            <option value="french">french</option>
            <option value="english">english</option>
            <option value="german">german</option>
            <option value="spanish">spanish</option>
          </select>
        </label>
        <label className="text-xs text-text-secondary">
          Limit
          <input type="number" min={1} max={50} value={config.limit} onChange={(e) => update('limit', parseInt(e.target.value))} className="w-full mt-1 bg-vault-800 border border-white/10 rounded px-2 py-1 text-text-primary text-sm" />
        </label>
      </div>
      <label className="flex items-center gap-2 mt-3 text-xs text-text-secondary">
        <input type="checkbox" checked={config.rerank} onChange={(e) => update('rerank', e.target.checked)} className="rounded border-white/20" />
        Enable re-ranking
      </label>
    </div>
  );
}

function DiffCard({ label, count, color, bg }: { label: string; count: number; color: string; bg: string }) {
  return (
    <div className={`${bg} border border-white/[0.06] rounded-lg p-4 text-center`}>
      <div className={`text-2xl font-bold ${color}`}>{count}</div>
      <div className="text-xs text-text-muted mt-1">{label}</div>
    </div>
  );
}

function VariantResults({ title, data, commonSet, highlight }: { title: string; data: VariantResult; commonSet: Set<string>; highlight: string }) {
  const hlBorder = highlight === 'amber' ? 'border-amber-400/30' : 'border-blue-400/30';
  const hlBg = highlight === 'amber' ? 'bg-amber-500/5' : 'bg-blue-500/5';

  return (
    <div className="bg-vault-900/60 border border-white/[0.06] rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
        <span className="text-xs text-text-muted">{data.elapsed_ms}ms · {data.results.length} results</span>
      </div>

      {Object.entries(data.source_counts).length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {Object.entries(data.source_counts).map(([source, count]) => (
            <span key={source} className="text-xs bg-vault-800 text-text-secondary rounded px-2 py-0.5 border border-white/5">
              {source}: {count}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-2 max-h-[600px] overflow-y-auto pr-1">
        {data.results.map((r) => {
          const isCommon = commonSet.has(r.document_id);
          return (
            <div key={r.document_id} className={`rounded border p-2 text-sm ${isCommon ? 'border-emerald-400/20 bg-emerald-500/5' : `${hlBorder} ${hlBg}`}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-text-primary truncate">{r.document_name}</span>
                <span className="text-xs text-text-muted tabular-nums shrink-0">{Math.round(r.final_score * 100)}%</span>
              </div>
              <p className="text-xs text-text-secondary mt-1 line-clamp-2">{r.chunk_text}</p>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[10px] bg-vault-800 text-text-muted rounded px-1.5 py-0.5">{r.match_source}</span>
                {!isCommon && <span className="text-[10px] text-amber-400">unique</span>}
              </div>
            </div>
          );
        })}
        {data.results.length === 0 && (
          <div className="text-xs text-text-muted text-center py-4">No results</div>
        )}
      </div>
    </div>
  );
}
