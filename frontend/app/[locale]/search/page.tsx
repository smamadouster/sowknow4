'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { getCsrfToken } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import VoiceRecorder from '@/components/VoiceRecorder';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

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

const RELEVANCE_TIERS = ['highly_relevant', 'relevant', 'partially', 'marginal'] as const;

const RELEVANCE_COLOR: Record<string, { dot: string; text: string; border: string; bg: string }> = {
  highly_relevant: { dot: 'bg-teal-400', text: 'text-teal-400', border: 'border-l-teal-400', bg: 'bg-teal-500/5' },
  relevant:        { dot: 'bg-blue-400', text: 'text-blue-400', border: 'border-l-blue-400', bg: 'bg-blue-500/5' },
  partially:       { dot: 'bg-amber-400', text: 'text-amber-400', border: 'border-l-amber-400', bg: 'bg-amber-500/5' },
  marginal:        { dot: 'bg-vault-500', text: 'text-text-muted', border: 'border-l-vault-500', bg: 'bg-vault-800/30' },
};

const INTENT_ICONS: Record<string, string> = {
  factual: '◆', temporal: '◷', comparative: '⇄', synthesis: '⊕', financial: '₣',
  cross_reference: '⊗', exploratory: '◉', entity_search: '◈', procedural: '▷', unknown: '○',
};

const INTENT_TYPES = Object.keys(INTENT_ICONS);

const TYPE_BADGE_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  document: { bg: 'bg-blue-500/10 text-blue-400', text: 'text-blue-400', icon: '□' },
  bookmark: { bg: 'bg-purple-500/10 text-purple-400', text: 'text-purple-400', icon: '★' },
  note:     { bg: 'bg-emerald-500/10 text-emerald-400', text: 'text-emerald-400', icon: '✎' },
  space:    { bg: 'bg-amber-500/10 text-amber-400', text: 'text-amber-400', icon: '◈' },
};

const SUGGESTION_ICONS: Record<string, string> = {
  related_query: '→', refine: '◎', expand: '⊕', temporal: '◷', entity_search: '◈',
};

function formatSynthesis(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\[Source: ([^\]]+)\]/g, '<cite class="text-xs text-text-muted not-italic border-b border-dashed border-white/10">[$1]</cite>')
    .replace(/^• (.+)$/gm, '<li class="mb-1">$1</li>')
    .replace(/\n/g, '<br/>');
}

function PipelineProgress({ stage, message }: { stage: PipelineStage; message: string }) {
  const stages: PipelineStage[] = ['intent', 'retrieval', 'reranking', 'synthesis', 'done'];
  const currentIdx = stages.indexOf(stage);
  if (stage === 'idle' || stage === 'error') return null;

  return (
    <div className="bg-vault-900/60 border border-white/[0.06] rounded-xl px-5 py-3.5 mb-4">
      <div className="flex items-center mb-2">
        {stages.map((s, i) => (
          <div key={s} className="flex items-center flex-1">
            <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 transition-all duration-300 ${
              i < currentIdx ? 'bg-teal-400 scale-100' : i === currentIdx ? 'bg-amber-400 scale-125' : 'bg-vault-700'
            }`} />
            {i < stages.length - 1 && (
              <div className={`flex-1 h-0.5 transition-colors duration-300 ${i < currentIdx ? 'bg-teal-400/50' : 'bg-vault-700'}`} />
            )}
          </div>
        ))}
      </div>
      <p className="text-text-muted text-xs italic m-0">{message}</p>
    </div>
  );
}

function IntentBadge({ intent, confidenceLabel, intentLabel }: { intent: StreamState['intent']; confidenceLabel: string; intentLabel: string }) {
  if (!intent) return null;
  const icon = INTENT_ICONS[intent.type] || INTENT_ICONS.unknown;
  const keywords = intent.keywords ?? [];

  return (
    <div className="flex items-center flex-wrap gap-1.5 mt-2.5 px-1">
      <span className="inline-flex items-center gap-1 border border-blue-400/30 text-blue-400 rounded-full px-2.5 py-0.5 text-xs font-semibold">
        <span>{icon}</span> {intentLabel}
      </span>
      <span className="bg-vault-800 text-text-muted rounded-full px-2 py-0.5 text-xs">
        {Math.round(intent.confidence * 100)}% {confidenceLabel}
      </span>
      {keywords.map((kw) => (
        <span key={kw} className="bg-blue-500/10 text-blue-400 rounded px-1.5 py-0.5 text-xs font-mono">{kw}</span>
      ))}
    </div>
  );
}

function SynthesisBlock({ text, model, synthesizedAnswerLabel, ollamaLabel, minimaxLabel }: { text: string; model: string | null; synthesizedAnswerLabel: string; ollamaLabel: string; minimaxLabel: string }) {
  const [expanded, setExpanded] = useState(true);
  const isOllama = model?.toLowerCase().includes('ollama');

  return (
    <div className="bg-vault-800/40 border border-white/[0.06] rounded-xl mb-5 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06] bg-vault-800/30">
        <div className="flex items-center gap-2">
          <span className="text-emerald-400">⊕</span>
          <span className="text-xs font-bold text-text-primary uppercase tracking-wide">
            {synthesizedAnswerLabel}
          </span>
          {model && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold border ${
              isOllama
                ? 'bg-vault-1000 text-amber-400 border-amber-400/20'
                : 'bg-blue-500/10 text-blue-400 border-blue-400/20'
            }`}>
              {isOllama ? `🛡️ ${ollamaLabel}` : `❄️ ${minimaxLabel}`}
            </span>
          )}
        </div>
        <button onClick={() => setExpanded((e) => !e)} className="text-text-muted text-xs px-1.5 py-0.5 hover:text-text-secondary bg-transparent border-none cursor-pointer">
          {expanded ? '▲' : '▼'}
        </button>
      </div>
      {expanded && (
        <div className="px-5 py-4 text-sm leading-relaxed text-text-secondary" dangerouslySetInnerHTML={{ __html: formatSynthesis(text) }} />
      )}
    </div>
  );
}

function ResultCard({ result, rank, canSeeConfidential, confidentialLabel, relevanceTierLabel, locale }: { result: SearchResult; rank: number; canSeeConfidential: boolean; confidentialLabel: string; relevanceTierLabel: string; locale: string }) {
  const tier = result.relevance_label || 'marginal';
  const colors = RELEVANCE_COLOR[tier] || RELEVANCE_COLOR.marginal;
  const title = result.document_title || result.document_name || '—';
  const excerpt = result.excerpt || result.chunk_text || '';
  const opacity = tier === 'marginal' ? 'opacity-75' : 'opacity-100';

  const handleDownload = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      const res = await fetch(`/api/v1/documents/${result.document_id}/download`, { credentials: 'include' });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = title;
        document.body.appendChild(a); a.click();
        document.body.removeChild(a); URL.revokeObjectURL(url);
      }
    } catch (err) { console.error('Download failed:', err); }
  };

  return (
    <div className={`bg-vault-900/60 border border-white/[0.06] border-l-4 rounded-lg p-4 mb-2 transition-all hover:bg-vault-900/80 ${colors.border} ${opacity}`}>
      <div className="flex items-start gap-2.5 mb-2">
        <span className={`text-text-primary rounded px-1.5 py-0.5 text-xs font-bold flex-shrink-0 mt-0.5 bg-vault-700`}>#{rank}</span>
        <div className="flex-1 min-w-0">
          <Link href={`/${locale}/documents/${result.document_id}`} className="block text-sm font-semibold text-text-primary truncate hover:text-amber-400 transition-colors">{title}</Link>
          <span className="text-xs text-text-muted/50 tracking-wide">
            {result.document_type?.toUpperCase()}
            {result.page_number ? ` · p.${result.page_number}` : ''}
            {result.document_date ? ` · ${new Date(result.document_date).getFullYear()}` : ''}
          </span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {result.is_confidential && canSeeConfidential && (
            <span className="bg-vault-1000 text-amber-400 rounded px-1.5 py-0.5 text-xs font-semibold border border-amber-400/20">🔒 {confidentialLabel}</span>
          )}
          <span className={`text-xs font-semibold flex items-center gap-1 ${colors.text}`}>
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${colors.dot}`} />
            {relevanceTierLabel}
          </span>
          <span className="text-xs text-text-muted tabular-nums">{Math.round(result.relevance_score * 100)}%</span>
          <div className="flex items-center gap-1 ml-1">
            <Link href={`/${locale}/documents/${result.document_id}`} className="p-1 text-text-muted hover:text-amber-400 rounded transition-colors" title="View document">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
            </Link>
            <button onClick={handleDownload} className="p-1 text-text-muted hover:text-amber-400 rounded transition-colors" title="Download">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
            </button>
          </div>
        </div>
      </div>
      {excerpt && <p className="text-sm text-text-secondary leading-relaxed mb-1.5">{excerpt}</p>}
      {result.match_reason && <span className="text-xs text-text-muted/50 italic">↳ {result.match_reason}</span>}
      {result.highlights && result.highlights.length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          {result.highlights.slice(0, 2).map((h, i) => (
            <span key={i} className="text-xs text-text-secondary bg-amber-500/5 border-l-2 border-amber-400/30 pl-2 pr-2 py-0.5 rounded-r italic">&ldquo;{h.length > 100 ? h.slice(0, 97) + '\u2026' : h}&rdquo;</span>
          ))}
        </div>
      )}
      {result.tags && result.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {result.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="bg-vault-800 text-text-muted rounded px-1.5 py-0.5 text-xs">{tag}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function Suggestions({ suggestions, onSelect, label }: { suggestions: Suggestion[]; onSelect: (q: string) => void; label: string }) {
  if (!suggestions.length) return null;
  return (
    <div className="mt-6 pt-5 border-t border-dashed border-white/[0.06]">
      <p className="text-xs uppercase tracking-widest text-text-muted mb-2.5">{label}</p>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((s, i) => (
          <button key={i} onClick={() => onSelect(s.text)} title={s.rationale} className="inline-flex items-center gap-1.5 bg-vault-800/50 border border-white/[0.06] rounded-full px-3.5 py-1.5 text-sm text-text-secondary cursor-pointer hover:border-amber-400/30 hover:bg-amber-500/5 transition-colors">
            <span className="text-sm text-text-muted/50">{SUGGESTION_ICONS[s.suggestion_type || ''] || '→'}</span>
            {s.text}
          </button>
        ))}
      </div>
    </div>
  );
}

function CitationsPanel({ citations, open, onClose, sourcesLabel, relevanceLabel }: { citations: Citation[]; open: boolean; onClose: () => void; sourcesLabel: string; relevanceLabel: string }) {
  if (!open || !citations.length) return null;
  return (
    <div className="w-72 flex-shrink-0 bg-vault-900/60 border border-white/[0.06] rounded-xl overflow-hidden sticky top-5 max-h-[80vh] overflow-y-auto">
      <div className="flex justify-between items-center px-3.5 py-3 border-b border-white/[0.06] bg-vault-800/30 sticky top-0">
        <span className="text-xs font-bold uppercase tracking-wide text-text-primary">{sourcesLabel} ({citations.length})</span>
        <button onClick={onClose} className="text-text-muted hover:text-text-secondary bg-transparent border-none cursor-pointer text-sm leading-none">✕</button>
      </div>
      {citations.map((c, i) => {
        const docTitle = c.document_title || c.document_name || '—';
        return (
          <div key={String(c.document_id)} className="px-3.5 py-3 border-b border-white/[0.04] last:border-b-0">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="bg-vault-800 rounded w-5 h-5 flex items-center justify-center text-xs font-bold text-text-secondary flex-shrink-0">{i + 1}</span>
              <span className="text-xs font-semibold text-text-primary flex-1 truncate">{docTitle}</span>
              {c.bucket === 'confidential' && <span className="text-xs">🔒</span>}
            </div>
            {c.chunk_excerpt && <p className="text-xs text-text-muted italic leading-relaxed my-1">&ldquo;{c.chunk_excerpt}&rdquo;</p>}
            <span className="text-xs text-text-muted/50">{relevanceLabel}: {Math.round(c.relevance_score * 100)}%</span>
          </div>
        );
      })}
    </div>
  );
}

function TypeFilterChips({ active, onChange, counts, labels }: { active: ResultTypeFilter; onChange: (filter: ResultTypeFilter) => void; counts: Record<string, number>; labels: Record<string, string> }) {
  const filters: ResultTypeFilter[] = ['all', 'document', 'bookmark', 'note', 'space'];
  return (
    <div className="flex flex-wrap gap-2 mb-4">
      {filters.map((f) => {
        const isActive = active === f;
        const count = f === 'all' ? Object.values(counts).reduce((a, b) => a + b, 0) : (counts[f] || 0);
        const style = f !== 'all' ? TYPE_BADGE_STYLES[f] : null;
        return (
          <button key={f} onClick={() => onChange(f)} className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-all border ${
            isActive ? 'bg-vault-800 text-amber-400 border-amber-400/30' : 'bg-vault-900/60 text-text-muted border-white/[0.06] hover:border-white/[0.12]'
          }`}>
            {style && <span className="text-xs">{style.icon}</span>}
            {labels[f] || f}
            {count > 0 && (
              <span className={`rounded-full px-1.5 py-0 text-xs font-bold ${isActive ? 'bg-amber-400/20 text-amber-400' : 'bg-vault-800 text-text-muted/50'}`}>{count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function GlobalResultCard({ result, locale, labels }: { result: GlobalSearchResult; locale: string; labels: Record<string, string> }) {
  const style = TYPE_BADGE_STYLES[result.result_type] || TYPE_BADGE_STYLES.document;
  const linkHref = result.result_type === 'document' ? `/${locale}/documents/${result.id}` : result.result_type === 'bookmark' && result.url ? result.url : result.result_type === 'note' ? `/${locale}/notes` : result.result_type === 'space' ? `/${locale}/spaces/${result.id}` : '#';
  const isExternal = result.result_type === 'bookmark' && result.url;

  return (
    <div className="bg-vault-900/60 border border-white/[0.06] rounded-lg p-4 mb-2 transition-all hover:bg-vault-900/80">
      <div className="flex items-start gap-2.5 mb-2">
        <span className={`${style.bg} rounded px-2 py-0.5 text-xs font-bold flex-shrink-0 mt-0.5 uppercase`}>{style.icon} {labels[result.result_type] || result.result_type}</span>
        <div className="flex-1 min-w-0">
          {isExternal ? (
            <a href={result.url} target="_blank" rel="noopener noreferrer" className="block text-sm font-semibold text-text-primary truncate hover:text-amber-400 transition-colors">{result.title}</a>
          ) : (
            <Link href={linkHref} className="block text-sm font-semibold text-text-primary truncate hover:text-amber-400 transition-colors">{result.title}</Link>
          )}
        </div>
        {result.bucket === 'confidential' && <span className="bg-vault-1000 text-amber-400 rounded px-1.5 py-0.5 text-xs font-semibold flex-shrink-0 border border-amber-400/20">🔒</span>}
      </div>
      {result.description && <p className="text-sm text-text-secondary leading-relaxed mb-1.5 line-clamp-2">{result.description}</p>}
      {result.tags && result.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {result.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="bg-vault-800 text-text-muted rounded px-1.5 py-0.5 text-xs">{tag}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SearchPage() {
  const t = useTranslations('search');
  const params = useParams();
  const locale = (params.locale as string) || 'fr';
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const canSeeConfidential = user?.role === 'admin' || user?.role === 'superuser' || user?.can_access_confidential;

  const [query, setQuery] = useState(searchParams.get('q') || '');
  const [isSearching, setIsSearching] = useState(false);
  const [showCitations, setShowCitations] = useState(false);
  const [showVoiceSearch, setShowVoiceSearch] = useState(false);
  const [typeFilter, setTypeFilter] = useState<ResultTypeFilter>('all');
  const [stream, setStream] = useState<StreamState>({
    stage: 'idle', stageMessage: '', intent: null, results: [], synthesis: null, citations: [], suggestions: [], hasConfidential: false, totalFound: 0, modelUsed: null, globalResults: [],
  });

  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const runSearchWithQuery = useCallback(async (searchQuery: string, updateUrl = true) => {
    if (!searchQuery.trim() || isSearching) return;
    if (updateUrl) { router.push(`/${locale}/search?q=${encodeURIComponent(searchQuery)}`); }
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setIsSearching(true);
    setShowCitations(false);
    setStream({ stage: 'intent', stageMessage: t('stage.intent'), intent: null, results: [], synthesis: null, citations: [], suggestions: [], hasConfidential: false, totalFound: 0, modelUsed: null, globalResults: [] });

    fetch(`${API_BASE}/v1/search/global?q=${encodeURIComponent(searchQuery)}&types=bookmark,note,space`, { credentials: 'include', headers: { 'X-CSRF-Token': getCsrfToken() }, signal: abortRef.current.signal })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => { setStream((prev) => ({ ...prev, globalResults: (data.results || []) as GlobalSearchResult[] })); })
      .catch(() => {});

    try {
      const response = await fetch(`${API_BASE}/v1/search/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() }, credentials: 'include',
        body: JSON.stringify({ query: searchQuery, mode: 'auto', top_k: 12, include_suggestions: true }), signal: abortRef.current.signal,
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
          if (line.startsWith('event: ')) { lastEventName = line.slice(7).trim(); continue; }
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw || raw === '[DONE]') continue;

          try {
            const evt = JSON.parse(raw) as Record<string, unknown>;

            // --- Stage progress events ---
            if ('stage' in evt) {
              const stage = evt.stage as PipelineStage;
              setStream((prev) => {
                let msg = (evt.message as string) || '';
                if (stage === 'intent') msg = t('stage.intent');
                else if (stage === 'retrieval') msg = t('stage.retrieval', { count: prev.totalFound || 0 });
                else if (stage === 'reranking') msg = t('stage.reranking', { count: prev.results.length || 0 });
                else if (stage === 'synthesis') msg = t('stage.synthesis');
                return { ...prev, stage, stageMessage: msg };
              });
              continue;
            }

            // --- Intent: backend sends flat {intent, confidence, keywords, ...} ---
            if ('intent' in evt && evt.intent) {
              setStream((prev) => ({ ...prev, intent: {
                type: evt.intent as string,
                confidence: (evt.confidence as number) ?? 0,
                keywords: (evt.keywords as string[]) ?? [],
              }}));
            }

            // --- Results ---
            if (lastEventName === 'results' && 'results' in evt && Array.isArray(evt.results)) {
              setStream((prev) => ({ ...prev, results: [...prev.results, ...(evt.results as SearchResult[])] }));
            }

            // --- Synthesis: backend sends "answer" and "model" ---
            if (lastEventName === 'synthesis' && 'answer' in evt) {
              setStream((prev) => ({
                ...prev,
                synthesis: (prev.synthesis || '') + (evt.answer as string),
                modelUsed: (evt.model as string) ?? prev.modelUsed,
              }));
            }

            // --- Citations: backend sends "citations" (plural, array) ---
            if ('citations' in evt && Array.isArray(evt.citations)) {
              setStream((prev) => ({ ...prev, citations: evt.citations as Citation[] }));
            }

            // --- Suggestions ---
            if ('suggestions' in evt && evt.suggestions) {
              setStream((prev) => ({ ...prev, suggestions: evt.suggestions as Suggestion[] }));
            }

            // --- Scalar fields from results/done events ---
            if ('total_found' in evt) { setStream((prev) => ({ ...prev, totalFound: evt.total_found as number })); }
            if ('model' in evt && lastEventName === 'done') { setStream((prev) => ({ ...prev, modelUsed: evt.model as string })); }
            if ('has_confidential' in evt || 'has_confidential_results' in evt) {
              setStream((prev) => ({ ...prev, hasConfidential: ((evt.has_confidential ?? evt.has_confidential_results) as boolean) }));
            }

            // --- Error: backend sends "message" field in error events ---
            if (lastEventName === 'error') {
              const errMsg = (evt.message as string) || (evt.error as string) || t('error');
              setStream((prev) => ({ ...prev, stage: 'error', stageMessage: errMsg }));
            }
          } catch {}
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== 'AbortError') { setStream((prev) => ({ ...prev, stage: 'error', stageMessage: t('error') })); }
    } finally {
      setIsSearching(false);
      setStream((prev) => prev.stage !== 'error' ? { ...prev, stage: 'done' } : prev);
    }
  }, [isSearching, t, locale, router]);

  useEffect(() => {
    const q = searchParams.get('q');
    if (q && q !== query) { setQuery(q); runSearchWithQuery(q, false); }
    else if (q && q === query && stream.results.length === 0) { runSearchWithQuery(q, false); }
  }, []);

  const handleSubmit = (e: React.FormEvent) => { e.preventDefault(); runSearchWithQuery(query); };
  const handleSuggestion = (text: string) => { setQuery(text); runSearchWithQuery(text); };
  const handleExampleClick = (text: string) => { setQuery(text); inputRef.current?.focus(); };
  const hasResults = stream.results.length > 0 || stream.globalResults.length > 0;
  const typeCounts: Record<string, number> = { document: stream.results.length };
  for (const gr of stream.globalResults) { typeCounts[gr.result_type] = (typeCounts[gr.result_type] || 0) + 1; }
  const filteredGlobalResults = typeFilter === 'all' || typeFilter === 'document' ? stream.globalResults : stream.globalResults.filter((r) => r.result_type === typeFilter);
  const showDocumentResults = typeFilter === 'all' || typeFilter === 'document';
  const typeLabels: Record<string, string> = { all: t('typeFilter.all' as Parameters<typeof t>[0]), document: t('typeFilter.documents' as Parameters<typeof t>[0]), bookmark: t('typeFilter.bookmarks' as Parameters<typeof t>[0]), note: t('typeFilter.notes' as Parameters<typeof t>[0]), space: t('typeFilter.spaces' as Parameters<typeof t>[0]) };

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto pb-20">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400/20 to-amber-600/5 border border-amber-400/20 flex items-center justify-center">
          <span className="text-amber-400 text-lg">⊛</span>
        </div>
        <div>
          <h1 className="text-xl font-bold text-text-primary tracking-tight font-display">{t('title')}</h1>
        </div>
        {stream.hasConfidential && canSeeConfidential && (
          <div className="ml-auto bg-vault-1000 text-amber-400 px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide border border-amber-400/20">🔒 {t('confidentialNotice')}</div>
        )}
      </div>

      {/* Search form */}
      <form onSubmit={handleSubmit} className="mb-2">
        <div className="flex items-center bg-vault-800/50 border border-white/[0.08] rounded-xl px-4 shadow-card focus-within:border-amber-400/30 focus-within:ring-2 focus-within:ring-amber-500/10 transition-all">
          <span className="text-lg text-text-muted/40 mr-2 flex-shrink-0">⌕</span>
          <input ref={inputRef} type="text" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runSearchWithQuery(query); } }} placeholder={t('placeholder')} disabled={isSearching} autoFocus className="flex-1 border-none outline-none bg-transparent text-sm text-text-primary py-3.5 placeholder:text-text-muted/40" />
          <button
            type="button"
            onClick={() => setShowVoiceSearch((v) => !v)}
            className={`flex-shrink-0 p-2 rounded-lg mr-1 transition-colors ${
              showVoiceSearch
                ? 'bg-amber-500/20 text-amber-400'
                : 'text-text-muted/40 hover:text-amber-400 hover:bg-amber-500/10'
            }`}
            title={t('voiceSearch')}
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
            </svg>
          </button>
          {isSearching ? (
            <button type="button" onClick={() => abortRef.current?.abort()} className="bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg px-3.5 py-2 text-xs font-bold cursor-pointer flex-shrink-0 hover:bg-red-500/30 transition-colors">■ {t('stop')}</button>
          ) : (
            <button type="submit" disabled={!query.trim()} className="bg-gradient-to-r from-amber-500 to-amber-600 text-vault-1000 border-none rounded-lg px-4 py-2 text-xs font-bold cursor-pointer flex-shrink-0 disabled:opacity-40 hover:from-amber-400 hover:to-amber-500 transition-all shadow-lg shadow-amber-500/20">
              {t('searchButton')} →
            </button>
          )}
        </div>
        {stream.intent && (
          <IntentBadge intent={stream.intent} confidenceLabel={t('confidence')} intentLabel={t((`intent.${INTENT_TYPES.includes(stream.intent.type) ? stream.intent.type : 'unknown'}`) as Parameters<typeof t>[0])} />
        )}
      </form>

      {showVoiceSearch && (
        <div className="mb-2 p-3 bg-vault-800/50 border border-white/[0.06] rounded-xl">
          <VoiceRecorder
            mode="search"
            onTranscript={(text) => {
              if (text.trim()) {
                setQuery(text);
                setShowVoiceSearch(false);
                runSearchWithQuery(text);
              }
            }}
            onCancel={() => setShowVoiceSearch(false)}
          />
        </div>
      )}

      <PipelineProgress stage={stream.stage} message={stream.stageMessage} />

      {stream.stage === 'error' && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-300 rounded-lg px-4 py-3 text-sm mb-4">⚠ {stream.stageMessage || t('error')}</div>
      )}

      {(hasResults || stream.synthesis) && (
        <div className="mt-2">
          <TypeFilterChips active={typeFilter} onChange={setTypeFilter} counts={typeCounts} labels={typeLabels} />

          <div className="flex items-center gap-3 mb-4">
            <span className="text-sm text-text-muted font-medium">{stream.totalFound + stream.globalResults.length} {stream.totalFound + stream.globalResults.length === 1 ? t('result') : t('resultsPlural')}</span>
            {stream.citations.length > 0 && (
              <button onClick={() => setShowCitations((v) => !v)} className="bg-vault-800/50 border border-white/[0.06] rounded-lg px-3 py-1 text-xs text-text-secondary cursor-pointer font-medium hover:bg-vault-800 transition-colors">⊞ {stream.citations.length} {stream.citations.length === 1 ? t('source') : t('sources')}</button>
            )}
          </div>

          <div className="flex gap-5 items-start">
            <div className="flex-1 min-w-0">
              {stream.synthesis && (
                <SynthesisBlock text={stream.synthesis} model={stream.modelUsed} synthesizedAnswerLabel={t('synthesizedAnswer')} ollamaLabel={t('model.ollama')} minimaxLabel={t('model.minimax')} />
              )}

              {showDocumentResults && RELEVANCE_TIERS.map((tier) => {
                const tierResults = stream.results.filter((r) => r.relevance_label === tier);
                if (!tierResults.length) return null;
                const colors = RELEVANCE_COLOR[tier];
                const labelKey = (`relevanceLabel.${tier}`) as Parameters<typeof t>[0];
                return (
                  <div key={tier} className="mb-5">
                    <div className="flex items-center mb-2 text-xs uppercase tracking-widest">
                      <span className={`inline-block w-2 h-2 rounded-full ${colors.dot} mr-1.5`} />
                      <span className={`font-semibold ${colors.text}`}>{t(labelKey)}</span>
                      <span className="ml-1.5 bg-vault-800 rounded-full px-1.5 py-0.5 text-text-muted">{tierResults.length}</span>
                    </div>
                    {tierResults.map((result, idx) => (
                      <ResultCard key={String(result.document_id) + idx} result={result} rank={result.rank ?? idx + 1} canSeeConfidential={!!canSeeConfidential} confidentialLabel={t('confidential')} relevanceTierLabel={t(labelKey)} locale={locale} />
                    ))}
                  </div>
                );
              })}

              {filteredGlobalResults.length > 0 && (
                <div className="mb-5">
                  {!showDocumentResults && (
                    <div className="flex items-center mb-2 text-xs uppercase tracking-widest">
                      <span className="font-semibold text-text-secondary">{typeLabels[typeFilter] || typeFilter}</span>
                      <span className="ml-1.5 bg-vault-800 rounded-full px-1.5 py-0.5 text-text-muted">{filteredGlobalResults.length}</span>
                    </div>
                  )}
                  {typeFilter === 'all' && filteredGlobalResults.length > 0 && (
                    <div className="flex items-center mb-2 text-xs uppercase tracking-widest">
                      <span className="font-semibold text-text-muted">{t('typeFilter.otherResults' as Parameters<typeof t>[0])}</span>
                    </div>
                  )}
                  {filteredGlobalResults.map((result) => (
                    <GlobalResultCard key={`${result.result_type}-${result.id}`} result={result} locale={locale} labels={typeLabels} />
                  ))}
                </div>
              )}

              <Suggestions suggestions={stream.suggestions} onSelect={handleSuggestion} label={t('suggestions')} />
            </div>

            <CitationsPanel citations={stream.citations} open={showCitations} onClose={() => setShowCitations(false)} sourcesLabel={t('sources')} relevanceLabel={t('relevance')} />
          </div>
        </div>
      )}

      {/* Empty state */}
      {stream.stage === 'idle' && (
        <div className="text-center py-20 px-8">
          <div className="w-20 h-20 rounded-2xl bg-vault-800/50 border border-white/[0.06] flex items-center justify-center mx-auto mb-4">
            <span className="text-4xl text-text-muted/20">⊛</span>
          </div>
          <p className="text-xl font-bold text-text-secondary mb-2 font-display">{t('empty.title')}</p>
          <p className="text-sm text-text-muted leading-relaxed max-w-md mx-auto mb-8">{t('empty.subtitle')}</p>
          <div className="flex flex-wrap gap-2 justify-center max-w-2xl mx-auto">
            {(['1', '2', '3', '4'] as const).map((n) => {
              const exKey = (`examples.${n}`) as Parameters<typeof t>[0];
              return (
                <button key={n} onClick={() => handleExampleClick(t(exKey))} className="bg-vault-800/50 border border-white/[0.06] rounded-full px-4 py-2 text-sm text-text-secondary cursor-pointer hover:border-amber-400/30 hover:bg-amber-500/5 transition-colors text-left">
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
