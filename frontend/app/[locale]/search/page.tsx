'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { getCsrfToken } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

// ─── Constants ────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

// ─── Types ────────────────────────────────────────────────────────────────────

type PipelineStage = 'idle' | 'intent' | 'retrieval' | 'reranking' | 'synthesis' | 'done' | 'error';

type ResultTypeFilter = 'all' | 'document' | 'bookmark' | 'note' | 'space';

interface StreamState {
  stage: PipelineStage;
  stageMessage: string;
  intent: { type: string; confidence: number; keywords: string[] } | null;
  results: SearchResult[];
  synthesis: string | null;
  citations: Citation[];
  suggestions: Suggestion[];
  hasConfidential: boolean;
  totalFound: number;
  modelUsed: string | null;
  globalResults: GlobalSearchResult[];
}

interface SearchResult {
  document_id: string | number;
  document_title?: string;
  document_name?: string;
  document_type?: string;
  document_date?: string;
  document_bucket?: string;
  page_number?: number | null;
  relevance_score: number;
  relevance_label?: string;
  excerpt?: string;
  chunk_text?: string;
  match_reason?: string;
  highlights?: string[];
  tags?: string[];
  rank?: number;
  is_confidential?: boolean;
}

interface GlobalSearchResult {
  result_type: 'document' | 'bookmark' | 'note' | 'space';
  id: string;
  title: string;
  description: string;
  tags: string[];
  score: number;
  bucket?: string;
  url?: string;
  icon?: string;
}

interface Citation {
  document_id: string | number;
  document_title?: string;
  document_name?: string;
  bucket?: string;
  chunk_excerpt?: string;
  relevance_score: number;
}

interface Suggestion {
  text: string;
  suggestion_type?: string;
  rationale?: string;
}

// ─── Relevance tier config ────────────────────────────────────────────────────

const RELEVANCE_TIERS = ['highly_relevant', 'relevant', 'partially', 'marginal'] as const;

const RELEVANCE_COLOR: Record<string, { dot: string; label: string; text: string; border: string }> = {
  highly_relevant: { dot: 'bg-teal-500', label: 'text-teal-700', text: 'text-teal-600', border: 'border-l-teal-500' },
  relevant:        { dot: 'bg-blue-500', label: 'text-blue-700', text: 'text-blue-600', border: 'border-l-blue-500' },
  partially:       { dot: 'bg-amber-500', label: 'text-amber-700', text: 'text-amber-600', border: 'border-l-amber-500' },
  marginal:        { dot: 'bg-gray-400', label: 'text-gray-500', text: 'text-gray-400', border: 'border-l-gray-400' },
};

const RANK_BG: Record<string, string> = {
  highly_relevant: 'bg-teal-500',
  relevant:        'bg-blue-500',
  partially:       'bg-amber-500',
  marginal:        'bg-gray-400',
};

// ─── Intent icon map ──────────────────────────────────────────────────────────

const INTENT_ICONS: Record<string, string> = {
  factual:         '◆',
  temporal:        '◷',
  comparative:     '⇄',
  synthesis:       '⊕',
  financial:       '₣',
  cross_reference: '⊗',
  exploratory:     '◉',
  entity_search:   '◈',
  procedural:      '▷',
  unknown:         '○',
};

const TYPE_BADGE_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  document: { bg: 'bg-blue-100', text: 'text-blue-700', icon: '□' },
  bookmark: { bg: 'bg-purple-100', text: 'text-purple-700', icon: '★' },
  note:     { bg: 'bg-green-100', text: 'text-green-700', icon: '✎' },
  space:    { bg: 'bg-amber-100', text: 'text-amber-700', icon: '◈' },
};

const SUGGESTION_ICONS: Record<string, string> = {
  related_query: '→',
  refine:        '◎',
  expand:        '⊕',
  temporal:      '◷',
  entity_search: '◈',
};

// ─── SSE formatter ────────────────────────────────────────────────────────────

function formatSynthesis(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(
      /\[Source: ([^\]]+)\]/g,
      '<cite class="text-xs text-gray-400 not-italic border-b border-dashed border-gray-300">[$1]</cite>'
    )
    .replace(/^• (.+)$/gm, '<li class="mb-1">$1</li>')
    .replace(/\n/g, '<br/>');
}

// ─── PipelineProgress ─────────────────────────────────────────────────────────

function PipelineProgress({ stage, message }: { stage: PipelineStage; message: string }) {
  const stages: PipelineStage[] = ['intent', 'retrieval', 'reranking', 'synthesis', 'done'];
  const currentIdx = stages.indexOf(stage);

  if (stage === 'idle' || stage === 'error') return null;

  return (
    <div className="bg-gray-900 rounded-xl px-5 py-3.5 mb-4">
      <div className="flex items-center mb-2">
        {stages.map((s, i) => (
          <div key={s} className="flex items-center flex-1">
            <div
              className={[
                'w-2.5 h-2.5 rounded-full flex-shrink-0 transition-all duration-300',
                i < currentIdx
                  ? 'bg-teal-400 scale-100'
                  : i === currentIdx
                  ? 'bg-yellow-300 scale-125'
                  : 'bg-gray-600',
              ].join(' ')}
            />
            {i < stages.length - 1 && (
              <div
                className={[
                  'flex-1 h-0.5 transition-colors duration-300',
                  i < currentIdx ? 'bg-teal-400' : 'bg-gray-700',
                ].join(' ')}
              />
            )}
          </div>
        ))}
      </div>
      <p className="text-gray-400 text-xs italic m-0">{message}</p>
    </div>
  );
}

// ─── IntentBadge ──────────────────────────────────────────────────────────────

function IntentBadge({
  intent,
  confidenceLabel,
  intentLabel,
}: {
  intent: StreamState['intent'];
  confidenceLabel: string;
  intentLabel: string;
}) {
  if (!intent) return null;
  const icon = INTENT_ICONS[intent.type] || INTENT_ICONS.unknown;

  return (
    <div className="flex items-center flex-wrap gap-1.5 mt-2.5 px-1">
      <span className="inline-flex items-center gap-1 border-2 border-blue-500 text-blue-600 rounded-full px-2.5 py-0.5 text-xs font-semibold">
        <span>{icon}</span>
        {intentLabel}
      </span>
      <span className="bg-gray-100 text-gray-500 rounded-full px-2 py-0.5 text-xs">
        {Math.round(intent.confidence * 100)}% {confidenceLabel}
      </span>
      {intent.keywords.map((kw) => (
        <span key={kw} className="bg-blue-50 text-blue-700 rounded px-1.5 py-0.5 text-xs font-mono">
          {kw}
        </span>
      ))}
    </div>
  );
}

// ─── SynthesisBlock ───────────────────────────────────────────────────────────

function SynthesisBlock({
  text,
  model,
  synthesizedAnswerLabel,
  ollamaLabel,
  minimaxLabel,
}: {
  text: string;
  model: string | null;
  synthesizedAnswerLabel: string;
  ollamaLabel: string;
  minimaxLabel: string;
}) {
  const [expanded, setExpanded] = useState(true);
  const isOllama = model?.toLowerCase().includes('ollama');

  return (
    <div className="bg-white border-2 border-gray-900 rounded-xl mb-5 overflow-hidden shadow-[3px_3px_0_#111827]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center gap-2">
          <span className="text-emerald-600">⊕</span>
          <span className="text-xs font-bold text-gray-900 uppercase tracking-wide">
            {synthesizedAnswerLabel}
          </span>
          {model && (
            <span
              className={[
                'rounded-full px-2 py-0.5 text-xs font-semibold border',
                isOllama
                  ? 'bg-gray-900 text-yellow-300 border-yellow-300'
                  : 'bg-blue-50 text-blue-700 border-blue-200',
              ].join(' ')}
            >
              {isOllama ? `\uD83D\uDD12 ${ollamaLabel}` : `\u2746 ${minimaxLabel}`}
            </span>
          )}
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-gray-400 text-xs px-1.5 py-0.5 hover:text-gray-600 bg-transparent border-none cursor-pointer"
        >
          {expanded ? '▲' : '▼'}
        </button>
      </div>
      {expanded && (
        <div
          className="px-5 py-4 text-sm leading-relaxed text-gray-700"
          dangerouslySetInnerHTML={{ __html: formatSynthesis(text) }}
        />
      )}
    </div>
  );
}

// ─── ResultCard ───────────────────────────────────────────────────────────────

function ResultCard({
  result,
  rank,
  canSeeConfidential,
  confidentialLabel,
  relevanceTierLabel,
  locale,
}: {
  result: SearchResult;
  rank: number;
  canSeeConfidential: boolean;
  confidentialLabel: string;
  relevanceTierLabel: string;
  locale: string;
}) {
  const tier = result.relevance_label || 'marginal';
  const colors = RELEVANCE_COLOR[tier] || RELEVANCE_COLOR.marginal;
  const rankBg = RANK_BG[tier] || RANK_BG.marginal;
  const title = result.document_title || result.document_name || '—';
  const excerpt = result.excerpt || result.chunk_text || '';
  const opacity = tier === 'marginal' ? 'opacity-75' : 'opacity-100';

  const handleDownload = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const res = await fetch(`/api/v1/documents/${result.document_id}/download`, {
        credentials: 'include',
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = title;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      console.error('Download failed:', err);
    }
  };

  return (
    <div
      className={[
        'bg-white border border-gray-200 border-l-4 rounded-lg p-4 mb-2 transition-shadow hover:shadow-md',
        colors.border,
        opacity,
      ].join(' ')}
    >
      {/* Header row */}
      <div className="flex items-start gap-2.5 mb-2">
        <span className={`${rankBg} text-white rounded px-1.5 py-0.5 text-xs font-bold flex-shrink-0 mt-0.5`}>
          #{rank}
        </span>
        <div className="flex-1 min-w-0">
          <Link
            href={`/${locale}/documents/${result.document_id}`}
            className="block text-sm font-semibold text-gray-900 truncate hover:text-blue-600 hover:underline"
          >
            {title}
          </Link>
          <span className="text-xs text-gray-400 tracking-wide">
            {result.document_type?.toUpperCase()}
            {result.page_number ? ` · p.${result.page_number}` : ''}
            {result.document_date
              ? ` · ${new Date(result.document_date).getFullYear()}`
              : ''}
          </span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {result.is_confidential && canSeeConfidential && (
            <span className="bg-gray-900 text-yellow-300 rounded px-1.5 py-0.5 text-xs font-semibold">
              {'\uD83D\uDD12'} {confidentialLabel}
            </span>
          )}
          <span className={`text-xs font-semibold flex items-center gap-1 ${colors.text}`}>
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${colors.dot}`} />
            {relevanceTierLabel}
          </span>
          <span className="text-xs text-gray-400 tabular-nums">
            {Math.round(result.relevance_score * 100)}%
          </span>
          <div className="flex items-center gap-1 ml-1">
            <Link
              href={`/${locale}/documents/${result.document_id}`}
              className="p-1 text-gray-400 hover:text-blue-600 rounded"
              title="View document"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </Link>
            <button
              onClick={handleDownload}
              className="p-1 text-gray-400 hover:text-blue-600 rounded"
              title="Download"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Excerpt */}
      {excerpt && (
        <p className="text-sm text-gray-600 leading-relaxed mb-1.5">{excerpt}</p>
      )}

      {/* Match reason */}
      {result.match_reason && (
        <span className="text-xs text-gray-400 italic">{'\u21B3'} {result.match_reason}</span>
      )}

      {/* Highlights */}
      {result.highlights && result.highlights.length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          {result.highlights.slice(0, 2).map((h, i) => (
            <span
              key={i}
              className="text-xs text-gray-700 bg-yellow-50 border-l-2 border-yellow-300 pl-2 pr-2 py-0.5 rounded-r italic"
            >
              &ldquo;{h.length > 100 ? h.slice(0, 97) + '\u2026' : h}&rdquo;
            </span>
          ))}
        </div>
      )}

      {/* Tags */}
      {result.tags && result.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {result.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="bg-gray-100 text-gray-500 rounded px-1.5 py-0.5 text-xs">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Suggestions ──────────────────────────────────────────────────────────────

function Suggestions({
  suggestions,
  onSelect,
  label,
}: {
  suggestions: Suggestion[];
  onSelect: (q: string) => void;
  label: string;
}) {
  if (!suggestions.length) return null;

  return (
    <div className="mt-6 pt-5 border-t border-dashed border-gray-200">
      <p className="text-xs uppercase tracking-widest text-gray-400 mb-2.5">{label}</p>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((s, i) => (
          <button
            key={i}
            onClick={() => onSelect(s.text)}
            title={s.rationale}
            className="inline-flex items-center gap-1.5 bg-white border-2 border-gray-200 rounded-full px-3.5 py-1.5 text-sm text-gray-700 cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors"
          >
            <span className="text-sm text-gray-400">
              {SUGGESTION_ICONS[s.suggestion_type || ''] || '→'}
            </span>
            {s.text}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── CitationsPanel ───────────────────────────────────────────────────────────

function CitationsPanel({
  citations,
  open,
  onClose,
  sourcesLabel,
  relevanceLabel,
}: {
  citations: Citation[];
  open: boolean;
  onClose: () => void;
  sourcesLabel: string;
  relevanceLabel: string;
}) {
  if (!open || !citations.length) return null;

  return (
    <div className="w-72 flex-shrink-0 bg-white border border-gray-200 rounded-xl overflow-hidden sticky top-5 max-h-[80vh] overflow-y-auto">
      <div className="flex justify-between items-center px-3.5 py-3 border-b border-gray-100 bg-gray-50 sticky top-0">
        <span className="text-xs font-bold uppercase tracking-wide text-gray-900">
          {sourcesLabel} ({citations.length})
        </span>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-700 bg-transparent border-none cursor-pointer text-sm leading-none"
        >
          {'\u2715'}
        </button>
      </div>
      {citations.map((c, i) => {
        const docTitle = c.document_title || c.document_name || '—';
        return (
          <div key={String(c.document_id)} className="px-3.5 py-3 border-b border-gray-50 last:border-b-0">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="bg-gray-100 rounded w-5 h-5 flex items-center justify-center text-xs font-bold text-gray-700 flex-shrink-0">
                {i + 1}
              </span>
              <span className="text-xs font-semibold text-gray-900 flex-1 truncate">{docTitle}</span>
              {c.bucket === 'confidential' && (
                <span className="text-xs">{'\uD83D\uDD12'}</span>
              )}
            </div>
            {c.chunk_excerpt && (
              <p className="text-xs text-gray-500 italic leading-relaxed my-1">
                &ldquo;{c.chunk_excerpt}&rdquo;
              </p>
            )}
            <span className="text-xs text-gray-400">
              {relevanceLabel}: {Math.round(c.relevance_score * 100)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── TypeFilterChips ─────────────────────────────────────────────────────────

function TypeFilterChips({
  active,
  onChange,
  counts,
  labels,
}: {
  active: ResultTypeFilter;
  onChange: (filter: ResultTypeFilter) => void;
  counts: Record<string, number>;
  labels: Record<string, string>;
}) {
  const filters: ResultTypeFilter[] = ['all', 'document', 'bookmark', 'note', 'space'];

  return (
    <div className="flex flex-wrap gap-2 mb-4">
      {filters.map((f) => {
        const isActive = active === f;
        const count = f === 'all'
          ? Object.values(counts).reduce((a, b) => a + b, 0)
          : (counts[f] || 0);
        const style = f !== 'all' ? TYPE_BADGE_STYLES[f] : null;

        return (
          <button
            key={f}
            onClick={() => onChange(f)}
            className={[
              'inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-all border-2',
              isActive
                ? 'bg-gray-900 text-white border-gray-900'
                : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400',
            ].join(' ')}
          >
            {style && <span className="text-xs">{style.icon}</span>}
            {labels[f] || f}
            {count > 0 && (
              <span
                className={[
                  'rounded-full px-1.5 py-0 text-xs font-bold',
                  isActive ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500',
                ].join(' ')}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ─── GlobalResultCard ────────────────────────────────────────────────────────

function GlobalResultCard({
  result,
  locale,
  labels,
}: {
  result: GlobalSearchResult;
  locale: string;
  labels: Record<string, string>;
}) {
  const style = TYPE_BADGE_STYLES[result.result_type] || TYPE_BADGE_STYLES.document;
  const linkHref = result.result_type === 'document'
    ? `/${locale}/documents/${result.id}`
    : result.result_type === 'bookmark' && result.url
    ? result.url
    : result.result_type === 'note'
    ? `/${locale}/notes`
    : result.result_type === 'space'
    ? `/${locale}/spaces/${result.id}`
    : '#';
  const isExternal = result.result_type === 'bookmark' && result.url;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-2 transition-shadow hover:shadow-md">
      <div className="flex items-start gap-2.5 mb-2">
        {/* Type badge */}
        <span
          className={`${style.bg} ${style.text} rounded px-2 py-0.5 text-xs font-bold flex-shrink-0 mt-0.5 uppercase`}
        >
          {style.icon} {labels[result.result_type] || result.result_type}
        </span>
        <div className="flex-1 min-w-0">
          {isExternal ? (
            <a
              href={result.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-sm font-semibold text-gray-900 truncate hover:text-blue-600 hover:underline"
            >
              {result.title}
            </a>
          ) : (
            <Link
              href={linkHref}
              className="block text-sm font-semibold text-gray-900 truncate hover:text-blue-600 hover:underline"
            >
              {result.title}
            </Link>
          )}
        </div>
        {result.bucket === 'confidential' && (
          <span className="bg-gray-900 text-yellow-300 rounded px-1.5 py-0.5 text-xs font-semibold flex-shrink-0">
            {'\uD83D\uDD12'}
          </span>
        )}
      </div>
      {result.description && (
        <p className="text-sm text-gray-600 leading-relaxed mb-1.5 line-clamp-2">
          {result.description}
        </p>
      )}
      {result.tags && result.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {result.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="bg-gray-100 text-gray-500 rounded px-1.5 py-0.5 text-xs">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── MAIN SEARCH PAGE ─────────────────────────────────────────────────────────

export default function SearchPage() {
  const t = useTranslations('search');
  const params = useParams();
  const locale = (params.locale as string) || 'fr';
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const canSeeConfidential =
    user?.role === 'admin' || user?.role === 'superuser' || user?.can_access_confidential;

  const [query, setQuery] = useState(searchParams.get('q') || '');
  const [isSearching, setIsSearching] = useState(false);
  const [showCitations, setShowCitations] = useState(false);
  const [typeFilter, setTypeFilter] = useState<ResultTypeFilter>('all');
  const [stream, setStream] = useState<StreamState>({
    stage: 'idle',
    stageMessage: '',
    intent: null,
    results: [],
    synthesis: null,
    citations: [],
    suggestions: [],
    hasConfidential: false,
    totalFound: 0,
    modelUsed: null,
    globalResults: [],
  });

  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const runSearchWithQuery = useCallback(
    async (searchQuery: string, updateUrl = true) => {
      if (!searchQuery.trim() || isSearching) return;

      if (updateUrl) {
        const newUrl = `/${locale}/search?q=${encodeURIComponent(searchQuery)}`;
        router.push(newUrl);
      }

      abortRef.current?.abort();
      abortRef.current = new AbortController();

      setIsSearching(true);
      setShowCitations(false);
      setStream({
        stage: 'intent',
        stageMessage: t('stage.intent'),
        intent: null,
        results: [],
        synthesis: null,
        citations: [],
        suggestions: [],
        hasConfidential: false,
        totalFound: 0,
        modelUsed: null,
        globalResults: [],
      });

      // Fire global multi-type search in parallel (non-blocking)
      fetch(`${API_BASE}/v1/search/global?q=${encodeURIComponent(searchQuery)}&types=bookmark,note,space`, {
        credentials: 'include',
        headers: { 'X-CSRF-Token': getCsrfToken() },
        signal: abortRef.current.signal,
      })
        .then((res) => (res.ok ? res.json() : Promise.reject(res)))
        .then((data) => {
          setStream((prev) => ({
            ...prev,
            globalResults: (data.results || []) as GlobalSearchResult[],
          }));
        })
        .catch(() => {
          // Non-critical — document search is the primary path
        });

      try {
        const response = await fetch(`${API_BASE}/v1/search/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': getCsrfToken(),
          },
          credentials: 'include',
          body: JSON.stringify({
            query: searchQuery,
            mode: 'auto',
            top_k: 12,
            include_suggestions: true,
          }),
          signal: abortRef.current.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let lastEventName = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              lastEventName = line.slice(7).trim();
              continue;
            }
            if (!line.startsWith('data: ')) continue;
            const raw = line.slice(6).trim();
            if (!raw || raw === '[DONE]') continue;

            try {
              const event = JSON.parse(raw) as Record<string, unknown>;

              // Stage update
              if ('stage' in event) {
                const stage = event.stage as PipelineStage;
                let msg = (event.message as string) || '';
                if (stage === 'intent') {
                  msg = t('stage.intent');
                } else if (stage === 'retrieval') {
                  msg = t('stage.retrieval');
                } else if (stage === 'reranking') {
                  msg = t('stage.reranking');
                } else if (stage === 'synthesis') {
                  msg = t('stage.synthesis');
                }
                setStream((prev) => ({
                  ...prev,
                  stage,
                  stageMessage: msg,
                }));
                continue;
              }

              // Intent event
              if ('intent' in event && event.intent) {
                setStream((prev) => ({
                  ...prev,
                  intent: event.intent as StreamState['intent'],
                }));
              }

              // Results chunk
              if (lastEventName === 'results' && 'results' in event) {
                const newResults = event.results as SearchResult[];
                setStream((prev) => ({
                  ...prev,
                  results: [...prev.results, ...newResults],
                }));
              }

              // Synthesis chunk
              if (lastEventName === 'synthesis' && 'text' in event) {
                setStream((prev) => ({
                  ...prev,
                  synthesis: (prev.synthesis || '') + (event.text as string),
                }));
              }

              // Citation event
              if ('citation' in event && event.citation) {
                const cit = event.citation as Citation;
                setStream((prev) => ({
                  ...prev,
                  citations: [...prev.citations, cit],
                }));
              }

              // Suggestions event
              if ('suggestions' in event && event.suggestions) {
                setStream((prev) => ({
                  ...prev,
                  suggestions: event.suggestions as Suggestion[],
                }));
              }

              // Final metadata
              if ('total_found' in event) {
                setStream((prev) => ({
                  ...prev,
                  totalFound: event.total_found as number,
                }));
              }
              if ('model_used' in event) {
                setStream((prev) => ({
                  ...prev,
                  modelUsed: event.model_used as string,
                }));
              }
              if ('has_confidential' in event) {
                setStream((prev) => ({
                  ...prev,
                  hasConfidential: event.has_confidential as boolean,
                }));
              }

              // Error event
              if ('error' in event) {
                setStream((prev) => ({
                  ...prev,
                  stage: 'error',
                  stageMessage: (event.error as string) || t('error'),
                }));
              }
            } catch {
              // Ignore malformed SSE lines
            }
          }
        }
      } catch (err: unknown) {
        if ((err as Error).name !== 'AbortError') {
          setStream((prev) => ({
            ...prev,
            stage: 'error',
            stageMessage: t('error'),
          }));
        }
      } finally {
        setIsSearching(false);
        setStream((prev) =>
          prev.stage !== 'error' ? { ...prev, stage: 'done' } : prev
        );
      }
    },
    [isSearching, t, locale, router]
  );

  useEffect(() => {
    const q = searchParams.get('q');
    if (q && q !== query) {
      setQuery(q);
      runSearchWithQuery(q, false);
    } else if (q && q === query && stream.results.length === 0) {
      runSearchWithQuery(q, false);
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runSearchWithQuery(query);
  };

  const handleSuggestion = (text: string) => {
    setQuery(text);
    runSearchWithQuery(text);
  };

  const handleExampleClick = (text: string) => {
    setQuery(text);
    inputRef.current?.focus();
  };

  const hasResults = stream.results.length > 0 || stream.globalResults.length > 0;

  // Compute type counts for filter chips
  const typeCounts: Record<string, number> = { document: stream.results.length };
  for (const gr of stream.globalResults) {
    typeCounts[gr.result_type] = (typeCounts[gr.result_type] || 0) + 1;
  }

  // Filter global results by selected type
  const filteredGlobalResults = typeFilter === 'all' || typeFilter === 'document'
    ? stream.globalResults
    : stream.globalResults.filter((r) => r.result_type === typeFilter);

  const showDocumentResults = typeFilter === 'all' || typeFilter === 'document';

  const typeLabels: Record<string, string> = {
    all: t('typeFilter.all' as Parameters<typeof t>[0]),
    document: t('typeFilter.documents' as Parameters<typeof t>[0]),
    bookmark: t('typeFilter.bookmarks' as Parameters<typeof t>[0]),
    note: t('typeFilter.notes' as Parameters<typeof t>[0]),
    space: t('typeFilter.spaces' as Parameters<typeof t>[0]),
  };

  return (
    <div className="p-6 max-w-5xl mx-auto pb-20">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 mb-8">
        <span className="text-3xl font-black text-gray-900 leading-none">{'\u229B'}</span>
        <div>
          <h1 className="text-2xl font-extrabold text-gray-900 tracking-tight">{t('title')}</h1>
        </div>
        {stream.hasConfidential && canSeeConfidential && (
          <div className="ml-auto bg-gray-900 text-yellow-300 px-3.5 py-1.5 rounded-lg text-xs font-semibold tracking-wide">
            {'\uD83D\uDD12'} {t('confidentialNotice')}
          </div>
        )}
      </div>

      {/* ── Search form ─────────────────────────────────────────────── */}
      <form onSubmit={handleSubmit} className="mb-2">
        <div className="flex items-center bg-white border-2 border-gray-900 rounded-xl px-4 shadow-[4px_4px_0_#111827]">
          <span className="text-xl text-gray-400 mr-2 flex-shrink-0">{'\u2315'}</span>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                runSearchWithQuery(query);
              }
            }}
            placeholder={t('placeholder')}
            disabled={isSearching}
            autoFocus
            className="flex-1 border-none outline-none bg-transparent text-sm text-gray-900 py-3.5 placeholder:text-gray-400"
          />
          {isSearching ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="bg-rose-500 text-white border-none rounded-lg px-3.5 py-2 text-xs font-bold cursor-pointer flex-shrink-0"
            >
              {'\u25A0'} {t('stop')}
            </button>
          ) : (
            <button
              type="submit"
              disabled={!query.trim()}
              className="bg-gray-900 text-yellow-300 border-none rounded-lg px-4 py-2 text-xs font-bold cursor-pointer flex-shrink-0 disabled:opacity-40 hover:bg-gray-800 transition-colors"
            >
              {t('searchButton')} {'\u2192'}
            </button>
          )}
        </div>

        {/* Intent badge */}
        {stream.intent && (
          <IntentBadge
            intent={stream.intent}
            confidenceLabel={t('confidence')}
            intentLabel={
              t((`intent.${stream.intent.type}`) as Parameters<typeof t>[0])
            }
          />
        )}
      </form>

      {/* ── Pipeline progress ──────────────────────────────────────── */}
      <PipelineProgress stage={stream.stage} message={stream.stageMessage} />

      {/* ── Error state ────────────────────────────────────────────── */}
      {stream.stage === 'error' && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm mb-4">
          {'\u26A0'} {stream.stageMessage || t('error')}
        </div>
      )}

      {/* ── Results area ───────────────────────────────────────────── */}
      {(hasResults || stream.synthesis) && (
        <div className="mt-2">
          {/* Type filter chips */}
          <TypeFilterChips
            active={typeFilter}
            onChange={setTypeFilter}
            counts={typeCounts}
            labels={typeLabels}
          />

          {/* Results header */}
          <div className="flex items-center gap-3 mb-4">
            <span className="text-sm text-gray-500 font-medium">
              {stream.totalFound + stream.globalResults.length}{' '}
              {stream.totalFound + stream.globalResults.length === 1 ? t('result') : t('resultsPlural')}
            </span>
            {stream.citations.length > 0 && (
              <button
                onClick={() => setShowCitations((v) => !v)}
                className="bg-gray-100 border border-gray-200 rounded-lg px-3 py-1 text-xs text-gray-700 cursor-pointer font-medium hover:bg-gray-200 transition-colors"
              >
                {'\u229E'} {stream.citations.length} {stream.citations.length === 1 ? t('source') : t('sources')}
              </button>
            )}
          </div>

          {/* Main grid: results left, citations right */}
          <div className="flex gap-5 items-start">
            {/* Results column */}
            <div className="flex-1 min-w-0">
              {/* Synthesized answer */}
              {stream.synthesis && (
                <SynthesisBlock
                  text={stream.synthesis}
                  model={stream.modelUsed}
                  synthesizedAnswerLabel={t('synthesizedAnswer')}
                  ollamaLabel={t('model.ollama')}
                  minimaxLabel={t('model.minimax')}
                />
              )}

              {/* Tiered document results */}
              {showDocumentResults && RELEVANCE_TIERS.map((tier) => {
                const tierResults = stream.results.filter((r) => r.relevance_label === tier);
                if (!tierResults.length) return null;
                const colors = RELEVANCE_COLOR[tier];
                const labelKey = (`relevanceLabel.${tier}`) as Parameters<typeof t>[0];
                return (
                  <div key={tier} className="mb-5">
                    <div className="flex items-center mb-2 text-xs uppercase tracking-widest">
                      <span className={`inline-block w-2 h-2 rounded-full ${colors.dot} mr-1.5`} />
                      <span className={`font-semibold ${colors.label}`}>{t(labelKey)}</span>
                      <span className="ml-1.5 bg-gray-100 rounded-full px-1.5 py-0.5 text-gray-500">
                        {tierResults.length}
                      </span>
                    </div>
                    {tierResults.map((result, idx) => (
                      <ResultCard
                        key={String(result.document_id) + idx}
                        result={result}
                        rank={result.rank ?? idx + 1}
                        canSeeConfidential={!!canSeeConfidential}
                        confidentialLabel={t('confidential')}
                        relevanceTierLabel={t(labelKey)}
                        locale={locale}
                      />
                    ))}
                  </div>
                );
              })}

              {/* Global results (bookmarks, notes, spaces) */}
              {filteredGlobalResults.length > 0 && (
                <div className="mb-5">
                  {!showDocumentResults && (
                    <div className="flex items-center mb-2 text-xs uppercase tracking-widest">
                      <span className="font-semibold text-gray-600">
                        {typeLabels[typeFilter] || typeFilter}
                      </span>
                      <span className="ml-1.5 bg-gray-100 rounded-full px-1.5 py-0.5 text-gray-500">
                        {filteredGlobalResults.length}
                      </span>
                    </div>
                  )}
                  {typeFilter === 'all' && filteredGlobalResults.length > 0 && (
                    <div className="flex items-center mb-2 text-xs uppercase tracking-widest">
                      <span className="font-semibold text-gray-500">
                        {t('typeFilter.otherResults' as Parameters<typeof t>[0])}
                      </span>
                    </div>
                  )}
                  {filteredGlobalResults.map((result) => (
                    <GlobalResultCard
                      key={`${result.result_type}-${result.id}`}
                      result={result}
                      locale={locale}
                      labels={typeLabels}
                    />
                  ))}
                </div>
              )}

              {/* Suggestions */}
              <Suggestions
                suggestions={stream.suggestions}
                onSelect={handleSuggestion}
                label={t('suggestions')}
              />
            </div>

            {/* Citations sidebar */}
            <CitationsPanel
              citations={stream.citations}
              open={showCitations}
              onClose={() => setShowCitations(false)}
              sourcesLabel={t('sources')}
              relevanceLabel={t('relevance')}
            />
          </div>
        </div>
      )}

      {/* ── Empty state ────────────────────────────────────────────── */}
      {stream.stage === 'idle' && (
        <div className="text-center py-20 px-8">
          <div className="text-6xl mb-4 text-gray-200">{'\u229B'}</div>
          <p className="text-xl font-bold text-gray-900 mb-2">{t('empty.title')}</p>
          <p className="text-sm text-gray-500 leading-relaxed max-w-md mx-auto mb-8">
            {t('empty.subtitle')}
          </p>
          <div className="flex flex-wrap gap-2 justify-center max-w-2xl mx-auto">
            {(['1', '2', '3', '4'] as const).map((n) => {
              const exKey = (`examples.${n}`) as Parameters<typeof t>[0];
              return (
                <button
                  key={n}
                  onClick={() => handleExampleClick(t(exKey))}
                  className="bg-white border-2 border-gray-200 rounded-full px-4 py-2 text-sm text-gray-700 cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors text-left"
                >
                  {t(exKey)}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
