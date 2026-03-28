/**
 * SOWKNOW Agentic Search Page
 * ============================
 * Progressive SSE-driven search UI with:
 * - Live intent badge while typing
 * - Stage-by-stage pipeline progress
 * - Tiered results with relevance classification
 * - Synthesized answer with animated reveal
 * - Source citations with expand/collapse
 * - Follow-up suggestion chips
 * - Confidential badge (Admin/SuperUser only)
 * - French/English language support
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useTranslation } from "@/hooks/useTranslation";
import type {
  SearchResponse,
  SearchResult,
  SearchSuggestion,
  Citation,
  ParsedIntentEnum,
} from "@/types/search";

// ─── Types ─────────────────────────────────────────────────────────────────

type PipelineStage =
  | "idle"
  | "intent"
  | "retrieval"
  | "reranking"
  | "synthesis"
  | "done"
  | "error";

interface StreamState {
  stage: PipelineStage;
  stageMessage: string;
  intent: { type: string; confidence: number; keywords: string[] } | null;
  results: SearchResult[];
  synthesis: string | null;
  citations: Citation[];
  suggestions: SearchSuggestion[];
  hasConfidential: boolean;
  totalFound: number;
  modelUsed: string | null;
}

const RELEVANCE_CONFIG: Record<
  string,
  { label: string; color: string; dot: string }
> = {
  highly_relevant: {
    label: "Très pertinent",
    color: "#0D9488",
    dot: "#14B8A6",
  },
  relevant: { label: "Pertinent", color: "#2563EB", dot: "#3B82F6" },
  partially: { label: "Partiel", color: "#D97706", dot: "#F59E0B" },
  marginal: { label: "Marginal", color: "#9CA3AF", dot: "#D1D5DB" },
};

const INTENT_META: Record<
  string,
  { icon: string; label: string; color: string }
> = {
  factual: { icon: "◆", label: "Factuel", color: "#2563EB" },
  temporal: { icon: "◷", label: "Temporel", color: "#7C3AED" },
  comparative: { icon: "⇄", label: "Comparatif", color: "#0891B2" },
  synthesis: { icon: "⊕", label: "Synthèse", color: "#059669" },
  financial: { icon: "₣", label: "Financier", color: "#B45309" },
  cross_reference: { icon: "⊗", label: "Croisé", color: "#DC2626" },
  exploratory: { icon: "◉", label: "Exploratoire", color: "#6D28D9" },
  entity_search: { icon: "◈", label: "Entité", color: "#0F766E" },
  procedural: { icon: "▷", label: "Procédural", color: "#1D4ED8" },
  unknown: { icon: "○", label: "Général", color: "#6B7280" },
};

// ─── Stage progress bar ──────────────────────────────────────────────────────

function PipelineProgress({
  stage,
  message,
}: {
  stage: PipelineStage;
  message: string;
}) {
  const stages: PipelineStage[] = [
    "intent",
    "retrieval",
    "reranking",
    "synthesis",
    "done",
  ];
  const currentIdx = stages.indexOf(stage);

  if (stage === "idle" || stage === "error") return null;

  return (
    <div style={styles.pipelineBar}>
      <div style={styles.pipelineStages}>
        {stages.map((s, i) => (
          <div key={s} style={styles.pipelineStep}>
            <div
              style={{
                ...styles.pipelineNode,
                background:
                  i < currentIdx
                    ? "#14B8A6"
                    : i === currentIdx
                    ? "#FFEB3B"
                    : "#E5E7EB",
                transform: i === currentIdx ? "scale(1.3)" : "scale(1)",
                transition: "all 0.3s ease",
              }}
            />
            {i < stages.length - 1 && (
              <div
                style={{
                  ...styles.pipelineLine,
                  background:
                    i < currentIdx
                      ? "#14B8A6"
                      : "rgba(255,255,255,0.15)",
                }}
              />
            )}
          </div>
        ))}
      </div>
      <p style={styles.stageMessage}>{message}</p>
    </div>
  );
}

// ─── Intent badge ────────────────────────────────────────────────────────────

function IntentBadge({ intent }: { intent: StreamState["intent"] }) {
  if (!intent) return null;
  const meta = INTENT_META[intent.type] || INTENT_META.unknown;
  return (
    <div style={styles.intentRow}>
      <span
        style={{ ...styles.intentBadge, borderColor: meta.color, color: meta.color }}
      >
        <span style={styles.intentIcon}>{meta.icon}</span>
        {meta.label}
      </span>
      <span style={styles.confidencePill}>
        {Math.round(intent.confidence * 100)}% confiance
      </span>
      {intent.keywords.map((kw) => (
        <span key={kw} style={styles.kwChip}>
          {kw}
        </span>
      ))}
    </div>
  );
}

// ─── Synthesis answer block ──────────────────────────────────────────────────

function SynthesisBlock({
  text,
  model,
  language,
}: {
  text: string;
  model: string | null;
  language: string;
}) {
  const [expanded, setExpanded] = useState(true);
  const isOllama = model?.includes("ollama");

  return (
    <div style={styles.synthesisCard}>
      <div style={styles.synthesisHeader}>
        <div style={styles.synthesisTitleRow}>
          <span style={styles.synthesisIcon}>⊕</span>
          <span style={styles.synthesisTitle}>
            {language === "fr" ? "Réponse synthétisée" : "Synthesized Answer"}
          </span>
          {model && (
            <span
              style={{
                ...styles.modelBadge,
                background: isOllama ? "#1A1A2E" : "#EFF6FF",
                color: isOllama ? "#FFEB3B" : "#1D4ED8",
                border: isOllama
                  ? "1px solid #FFEB3B"
                  : "1px solid #BFDBFE",
              }}
            >
              {isOllama ? "🔒 Ollama" : "✦ Kimi 2.5"}
            </span>
          )}
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          style={styles.collapseBtn}
        >
          {expanded ? "▲" : "▼"}
        </button>
      </div>
      {expanded && (
        <div
          style={styles.synthesisBody}
          dangerouslySetInnerHTML={{
            __html: formatSynthesis(text),
          }}
        />
      )}
    </div>
  );
}

function formatSynthesis(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/\[Source: ([^\]]+)\]/g, '<cite style="font-size:0.78rem;color:#6B7280;font-style:normal;border-bottom:1px dashed #D1D5DB">[$1]</cite>')
    .replace(/^• (.+)$/gm, '<li style="margin-bottom:4px">$1</li>')
    .replace(/\n/g, "<br/>");
}

// ─── Single result card ──────────────────────────────────────────────────────

function ResultCard({
  result,
  rank,
  canSeeConfidential,
}: {
  result: SearchResult;
  rank: number;
  canSeeConfidential: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rel = RELEVANCE_CONFIG[result.relevance_label] || RELEVANCE_CONFIG.marginal;

  return (
    <div
      style={{
        ...styles.resultCard,
        borderLeft: `3px solid ${rel.dot}`,
        opacity: result.relevance_label === "marginal" ? 0.75 : 1,
      }}
    >
      <div style={styles.resultHeader}>
        {/* Rank badge */}
        <span style={{ ...styles.rankBadge, background: rel.color }}>
          #{rank}
        </span>

        {/* Title */}
        <div style={styles.resultTitleBlock}>
          <span style={styles.resultTitle}>{result.document_title}</span>
          <span style={styles.resultMeta}>
            {result.document_type?.toUpperCase()}
            {result.page_number ? ` · p.${result.page_number}` : ""}
            {result.document_date
              ? ` · ${new Date(result.document_date).getFullYear()}`
              : ""}
          </span>
        </div>

        {/* Right side badges */}
        <div style={styles.badgeGroup}>
          {result.is_confidential && canSeeConfidential && (
            <span style={styles.confBadge}>🔒 Confidentiel</span>
          )}
          <span style={{ ...styles.relBadge, color: rel.color }}>
            <span
              style={{
                display: "inline-block",
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: rel.dot,
                marginRight: 4,
              }}
            />
            {rel.label}
          </span>
          <span style={styles.scoreText}>
            {Math.round(result.relevance_score * 100)}%
          </span>
        </div>
      </div>

      {/* Excerpt */}
      <p style={styles.excerpt}>{result.excerpt}</p>

      {/* Match reason */}
      <span style={styles.matchReason}>↳ {result.match_reason}</span>

      {/* Highlights */}
      {result.highlights?.length > 0 && (
        <div style={styles.highlightsRow}>
          {result.highlights.slice(0, 2).map((h, i) => (
            <span key={i} style={styles.highlight}>
              "{h.length > 100 ? h.slice(0, 97) + "…" : h}"
            </span>
          ))}
        </div>
      )}

      {/* Tags */}
      {result.tags?.length > 0 && (
        <div style={styles.tagsRow}>
          {result.tags.slice(0, 5).map((t) => (
            <span key={t} style={styles.tag}>
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Suggestions row ─────────────────────────────────────────────────────────

function Suggestions({
  suggestions,
  onSelect,
}: {
  suggestions: SearchSuggestion[];
  onSelect: (q: string) => void;
}) {
  if (!suggestions.length) return null;
  const icons: Record<string, string> = {
    related_query: "→",
    refine: "◎",
    expand: "⊕",
    temporal: "◷",
    entity_search: "◈",
  };
  return (
    <div style={styles.suggestionsSection}>
      <p style={styles.suggestionsLabel}>Suggestions</p>
      <div style={styles.suggestionsRow}>
        {suggestions.map((s, i) => (
          <button
            key={i}
            onClick={() => onSelect(s.text)}
            style={styles.suggestionChip}
            title={s.rationale}
          >
            <span style={styles.suggestionIcon}>
              {icons[s.suggestion_type] || "→"}
            </span>
            {s.text}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Citations sidebar ───────────────────────────────────────────────────────

function CitationsPanel({
  citations,
  open,
  onClose,
}: {
  citations: Citation[];
  open: boolean;
  onClose: () => void;
}) {
  if (!open || !citations.length) return null;
  return (
    <div style={styles.citationsPanel}>
      <div style={styles.citationsHeader}>
        <span>Sources ({citations.length})</span>
        <button onClick={onClose} style={styles.closeBtn}>
          ✕
        </button>
      </div>
      {citations.map((c, i) => (
        <div key={String(c.document_id)} style={styles.citationItem}>
          <div style={styles.citationTitleRow}>
            <span style={styles.citationNum}>{i + 1}</span>
            <span style={styles.citationTitle}>{c.document_title}</span>
            {c.bucket === "confidential" && (
              <span style={styles.confBadgeSmall}>🔒</span>
            )}
          </div>
          <p style={styles.citationExcerpt}>"{c.chunk_excerpt}"</p>
          <span style={styles.citationScore}>
            Pertinence: {Math.round(c.relevance_score * 100)}%
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── MAIN SEARCH PAGE ─────────────────────────────────────────────────────────

export default function SearchPage() {
  const { user } = useAuth();
  const canSeeConfidential =
    user?.role === "admin" || user?.role === "super_user";

  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [showCitations, setShowCitations] = useState(false);
  const [stream, setStream] = useState<StreamState>({
    stage: "idle",
    stageMessage: "",
    intent: null,
    results: [],
    synthesis: null,
    citations: [],
    suggestions: [],
    hasConfidential: false,
    totalFound: 0,
    modelUsed: null,
  });

  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const runSearch = useCallback(
    async (searchQuery: string) => {
      if (!searchQuery.trim() || isSearching) return;

      // Abort any in-flight search
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      setIsSearching(true);
      setShowCitations(false);
      setStream({
        stage: "intent",
        stageMessage: "Analyse de votre requête…",
        intent: null,
        results: [],
        synthesis: null,
        citations: [],
        suggestions: [],
        hasConfidential: false,
        totalFound: 0,
        modelUsed: null,
      });

      try {
        const response = await fetch("/api/search/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("sowknow_token")}`,
          },
          body: JSON.stringify({
            query: searchQuery,
            mode: "auto",
            top_k: 12,
            include_suggestions: true,
          }),
          signal: abortRef.current.signal,
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line.startsWith("event: ")) continue;
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;

            try {
              const event = JSON.parse(raw) as {
                event?: string;
                [key: string]: unknown;
              };
              // We also get the event name from the preceding line
              // Handle by payload shape
              if ("stage" in event) {
                setStream((prev) => ({
                  ...prev,
                  stage: event.stage as PipelineStage,
                  stageMessage: (event.message as string) || "",
                }));
              } else if ("intent" in event && "confidence" in event) {
                setStream((prev) => ({
                  ...prev,
                  intent: {
                    type: event.intent as string,
                    confidence: event.confidence as number,
                    keywords: (event.keywords as string[]) || [],
                  },
                }));
              } else if ("results" in event) {
                setStream((prev) => ({
                  ...prev,
                  results: event.results as SearchResult[],
                  totalFound: event.total_found as number,
                  hasConfidential: event.has_confidential_results as boolean,
                }));
              } else if ("answer" in event) {
                setStream((prev) => ({
                  ...prev,
                  synthesis: event.answer as string,
                  modelUsed: event.model as string,
                }));
              } else if ("suggestions" in event) {
                setStream((prev) => ({
                  ...prev,
                  suggestions: event.suggestions as SearchSuggestion[],
                }));
              } else if ("citations" in event) {
                setStream((prev) => ({
                  ...prev,
                  citations: event.citations as Citation[],
                }));
              } else if ("total_found" in event && !("results" in event)) {
                // done event
                setStream((prev) => ({ ...prev, stage: "done" }));
              }
            } catch {
              // Ignore malformed SSE lines
            }
          }
        }
      } catch (err: unknown) {
        if ((err as Error).name !== "AbortError") {
          setStream((prev) => ({
            ...prev,
            stage: "error",
            stageMessage: "La recherche a rencontré une erreur.",
          }));
        }
      } finally {
        setIsSearching(false);
        setStream((prev) =>
          prev.stage !== "error" ? { ...prev, stage: "done" } : prev
        );
      }
    },
    [isSearching]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runSearch(query);
  };

  const handleSuggestion = (text: string) => {
    setQuery(text);
    runSearch(text);
  };

  const hasResults = stream.results.length > 0;
  const isActive = stream.stage !== "idle";

  return (
    <div style={styles.page}>
      {/* ── Background noise texture ──────────────────────────────────── */}
      <div style={styles.bgNoise} />

      {/* ── Header ───────────────────────────────────────────────────── */}
      <div style={styles.header}>
        <div style={styles.logoMark}>⊛</div>
        <div>
          <h1 style={styles.pageTitle}>Recherche</h1>
          <p style={styles.pageSubtitle}>
            Interrogez votre mémoire en langage naturel
          </p>
        </div>
        {stream.hasConfidential && canSeeConfidential && (
          <div style={styles.confNotice}>
            🔒 Cette recherche inclut des documents confidentiels
          </div>
        )}
      </div>

      {/* ── Search form ───────────────────────────────────────────────── */}
      <form onSubmit={handleSubmit} style={styles.searchForm}>
        <div style={styles.inputWrapper}>
          <span style={styles.searchIcon}>⌕</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ex: Quels actifs avais-je en 2022 ? / How has my thinking on AI evolved?"
            style={styles.searchInput}
            disabled={isSearching}
            autoFocus
          />
          {isSearching ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              style={styles.stopBtn}
            >
              ■ Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!query.trim()}
              style={{
                ...styles.searchBtn,
                opacity: query.trim() ? 1 : 0.4,
              }}
            >
              Rechercher →
            </button>
          )}
        </div>

        {/* Intent badge (appears while typing after first search) */}
        {stream.intent && <IntentBadge intent={stream.intent} />}
      </form>

      {/* ── Pipeline progress ────────────────────────────────────────── */}
      <PipelineProgress
        stage={stream.stage}
        message={stream.stageMessage}
      />

      {/* ── Error state ───────────────────────────────────────────────── */}
      {stream.stage === "error" && (
        <div style={styles.errorBox}>
          ⚠ {stream.stageMessage || "Erreur de recherche"}
        </div>
      )}

      {/* ── Results area ─────────────────────────────────────────────── */}
      {(hasResults || stream.synthesis) && (
        <div style={styles.resultsArea}>
          {/* Results header */}
          <div style={styles.resultsHeader}>
            <span style={styles.resultsCount}>
              {stream.totalFound} résultat{stream.totalFound !== 1 ? "s" : ""}
            </span>
            {stream.citations.length > 0 && (
              <button
                onClick={() => setShowCitations((v) => !v)}
                style={styles.citationsBtn}
              >
                ⊞ {stream.citations.length} source
                {stream.citations.length !== 1 ? "s" : ""}
              </button>
            )}
          </div>

          {/* Main layout: results + citations side panel */}
          <div style={styles.mainGrid}>
            {/* ── Left: synthesis + results ──────────────────────── */}
            <div style={styles.resultsColumn}>
              {/* Synthesized answer */}
              {stream.synthesis && (
                <SynthesisBlock
                  text={stream.synthesis}
                  model={stream.modelUsed}
                  language={stream.intent?.type || "fr"}
                />
              )}

              {/* Results by tier */}
              {(["highly_relevant", "relevant", "partially", "marginal"] as const).map(
                (tier) => {
                  const tierResults = stream.results.filter(
                    (r) => r.relevance_label === tier
                  );
                  if (!tierResults.length) return null;
                  const conf = RELEVANCE_CONFIG[tier];
                  return (
                    <div key={tier} style={styles.tierSection}>
                      <div style={styles.tierHeader}>
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: "50%",
                            background: conf.dot,
                            display: "inline-block",
                            marginRight: 6,
                          }}
                        />
                        <span style={{ color: conf.color, fontWeight: 600 }}>
                          {conf.label}
                        </span>
                        <span style={styles.tierCount}>
                          {tierResults.length}
                        </span>
                      </div>
                      {tierResults.map((result) => (
                        <ResultCard
                          key={String(result.document_id)}
                          result={result}
                          rank={result.rank}
                          canSeeConfidential={canSeeConfidential}
                        />
                      ))}
                    </div>
                  );
                }
              )}

              {/* Suggestions */}
              <Suggestions
                suggestions={stream.suggestions}
                onSelect={handleSuggestion}
              />
            </div>

            {/* ── Right: citations panel ─────────────────────────── */}
            <CitationsPanel
              citations={stream.citations}
              open={showCitations}
              onClose={() => setShowCitations(false)}
            />
          </div>
        </div>
      )}

      {/* ── Empty state ───────────────────────────────────────────────── */}
      {stream.stage === "idle" && (
        <div style={styles.emptyState}>
          <div style={styles.emptyIcon}>⊛</div>
          <p style={styles.emptyTitle}>
            Votre connaissance vous attend
          </p>
          <p style={styles.emptySubtitle}>
            Posez une question en français ou en anglais. L'agent analysera
            votre requête, cherchera dans tous vos documents et synthétisera
            une réponse complète.
          </p>
          <div style={styles.exampleQueries}>
            {[
              "Comment a évolué ma réflexion sur l'énergie solaire ?",
              "Quels actifs figurent dans mes bilans des 5 dernières années ?",
              "Tous les documents liés à ma famille",
              "What insights do I have about leadership?",
            ].map((eq) => (
              <button
                key={eq}
                onClick={() => {
                  setQuery(eq);
                  inputRef.current?.focus();
                }}
                style={styles.exampleChip}
              >
                {eq}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    background: "#F8F9FA",
    fontFamily: "'DM Sans', 'Helvetica Neue', sans-serif",
    padding: "32px 24px 80px",
    maxWidth: 1100,
    margin: "0 auto",
    position: "relative",
  },
  bgNoise: {
    position: "fixed",
    inset: 0,
    opacity: 0.018,
    backgroundImage:
      "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E\")",
    pointerEvents: "none",
    zIndex: 0,
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    marginBottom: 32,
  },
  logoMark: {
    fontSize: 36,
    color: "#1A1A2E",
    lineHeight: 1,
    fontWeight: 900,
  },
  pageTitle: {
    fontSize: 28,
    fontWeight: 800,
    color: "#1A1A2E",
    margin: 0,
    letterSpacing: "-0.5px",
  },
  pageSubtitle: {
    fontSize: 13,
    color: "#6B7280",
    margin: "2px 0 0",
  },
  confNotice: {
    marginLeft: "auto",
    background: "#1A1A2E",
    color: "#FFEB3B",
    padding: "6px 14px",
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    letterSpacing: "0.3px",
  },
  searchForm: {
    marginBottom: 8,
  },
  inputWrapper: {
    display: "flex",
    alignItems: "center",
    background: "#FFFFFF",
    border: "2px solid #1A1A2E",
    borderRadius: 10,
    padding: "0 8px 0 16px",
    boxShadow: "4px 4px 0 #1A1A2E",
    transition: "box-shadow 0.15s ease",
  },
  searchIcon: {
    fontSize: 20,
    color: "#9CA3AF",
    marginRight: 8,
    flexShrink: 0,
  },
  searchInput: {
    flex: 1,
    border: "none",
    outline: "none",
    background: "transparent",
    fontSize: 15,
    color: "#1A1A2E",
    padding: "14px 0",
    fontFamily: "inherit",
  },
  searchBtn: {
    background: "#1A1A2E",
    color: "#FFEB3B",
    border: "none",
    borderRadius: 6,
    padding: "10px 18px",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
    flexShrink: 0,
    letterSpacing: "0.2px",
  },
  stopBtn: {
    background: "#E91E63",
    color: "#FFFFFF",
    border: "none",
    borderRadius: 6,
    padding: "10px 14px",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
    flexShrink: 0,
  },
  intentRow: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 10,
    padding: "0 4px",
  },
  intentBadge: {
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
    border: "1.5px solid",
    borderRadius: 20,
    padding: "3px 10px",
    fontSize: 12,
    fontWeight: 600,
    letterSpacing: "0.2px",
  },
  intentIcon: {
    fontSize: 14,
  },
  confidencePill: {
    background: "#F3F4F6",
    color: "#6B7280",
    borderRadius: 20,
    padding: "3px 8px",
    fontSize: 11,
  },
  kwChip: {
    background: "#EFF6FF",
    color: "#1D4ED8",
    borderRadius: 4,
    padding: "2px 7px",
    fontSize: 11,
    fontFamily: "monospace",
  },
  pipelineBar: {
    background: "#1A1A2E",
    borderRadius: 10,
    padding: "14px 20px",
    marginBottom: 16,
  },
  pipelineStages: {
    display: "flex",
    alignItems: "center",
    marginBottom: 8,
  },
  pipelineStep: {
    display: "flex",
    alignItems: "center",
    flex: 1,
  },
  pipelineNode: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    flexShrink: 0,
  },
  pipelineLine: {
    flex: 1,
    height: 2,
  },
  stageMessage: {
    color: "#9CA3AF",
    fontSize: 12,
    margin: 0,
    fontStyle: "italic",
  },
  errorBox: {
    background: "#FEF2F2",
    border: "1px solid #FECACA",
    color: "#DC2626",
    borderRadius: 8,
    padding: "12px 16px",
    fontSize: 14,
    marginBottom: 16,
  },
  resultsArea: {
    marginTop: 8,
  },
  resultsHeader: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    marginBottom: 16,
  },
  resultsCount: {
    fontSize: 13,
    color: "#6B7280",
    fontWeight: 500,
  },
  citationsBtn: {
    background: "#F3F4F6",
    border: "1px solid #E5E7EB",
    borderRadius: 6,
    padding: "4px 12px",
    fontSize: 12,
    color: "#374151",
    cursor: "pointer",
    fontWeight: 500,
  },
  mainGrid: {
    display: "flex",
    gap: 20,
    alignItems: "flex-start",
  },
  resultsColumn: {
    flex: 1,
    minWidth: 0,
  },
  synthesisCard: {
    background: "#FFFFFF",
    border: "2px solid #1A1A2E",
    borderRadius: 10,
    marginBottom: 20,
    overflow: "hidden",
    boxShadow: "3px 3px 0 #1A1A2E",
  },
  synthesisHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "12px 16px",
    borderBottom: "1px solid #F3F4F6",
    background: "#FAFAFA",
  },
  synthesisTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  synthesisIcon: {
    fontSize: 16,
    color: "#059669",
  },
  synthesisTitle: {
    fontSize: 13,
    fontWeight: 700,
    color: "#1A1A2E",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
  },
  modelBadge: {
    borderRadius: 20,
    padding: "2px 9px",
    fontSize: 11,
    fontWeight: 600,
  },
  collapseBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    color: "#9CA3AF",
    fontSize: 12,
    padding: "2px 6px",
  },
  synthesisBody: {
    padding: "16px 20px",
    fontSize: 14,
    lineHeight: 1.75,
    color: "#374151",
  },
  tierSection: {
    marginBottom: 20,
  },
  tierHeader: {
    display: "flex",
    alignItems: "center",
    marginBottom: 8,
    fontSize: 12,
    textTransform: "uppercase",
    letterSpacing: "0.6px",
  },
  tierCount: {
    marginLeft: 6,
    background: "#F3F4F6",
    borderRadius: 10,
    padding: "1px 7px",
    fontSize: 11,
    color: "#6B7280",
  },
  resultCard: {
    background: "#FFFFFF",
    border: "1px solid #E5E7EB",
    borderRadius: 8,
    padding: "14px 16px",
    marginBottom: 8,
    transition: "box-shadow 0.15s ease",
  },
  resultHeader: {
    display: "flex",
    alignItems: "flex-start",
    gap: 10,
    marginBottom: 8,
  },
  rankBadge: {
    color: "#FFFFFF",
    borderRadius: 4,
    padding: "2px 7px",
    fontSize: 11,
    fontWeight: 700,
    flexShrink: 0,
    marginTop: 2,
  },
  resultTitleBlock: {
    flex: 1,
    minWidth: 0,
  },
  resultTitle: {
    display: "block",
    fontSize: 14,
    fontWeight: 600,
    color: "#1A1A2E",
    marginBottom: 2,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  resultMeta: {
    fontSize: 11,
    color: "#9CA3AF",
    letterSpacing: "0.3px",
  },
  badgeGroup: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexShrink: 0,
  },
  confBadge: {
    background: "#1A1A2E",
    color: "#FFEB3B",
    borderRadius: 4,
    padding: "2px 6px",
    fontSize: 10,
    fontWeight: 600,
  },
  confBadgeSmall: {
    fontSize: 11,
  },
  relBadge: {
    fontSize: 11,
    fontWeight: 600,
    display: "flex",
    alignItems: "center",
  },
  scoreText: {
    fontSize: 11,
    color: "#9CA3AF",
    fontVariantNumeric: "tabular-nums",
  },
  excerpt: {
    fontSize: 13,
    color: "#4B5563",
    lineHeight: 1.6,
    margin: "0 0 6px",
  },
  matchReason: {
    fontSize: 11,
    color: "#9CA3AF",
    fontStyle: "italic",
  },
  highlightsRow: {
    marginTop: 8,
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  highlight: {
    fontSize: 12,
    color: "#374151",
    background: "#FEFCE8",
    borderLeft: "2px solid #FFEB3B",
    padding: "3px 8px",
    borderRadius: "0 4px 4px 0",
    fontStyle: "italic",
  },
  tagsRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 8,
  },
  tag: {
    background: "#F3F4F6",
    color: "#6B7280",
    borderRadius: 4,
    padding: "2px 7px",
    fontSize: 11,
  },
  suggestionsSection: {
    marginTop: 24,
    paddingTop: 20,
    borderTop: "1px dashed #E5E7EB",
  },
  suggestionsLabel: {
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.6px",
    color: "#9CA3AF",
    marginBottom: 10,
  },
  suggestionsRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  suggestionChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    background: "#FFFFFF",
    border: "1.5px solid #E5E7EB",
    borderRadius: 20,
    padding: "7px 14px",
    fontSize: 13,
    color: "#374151",
    cursor: "pointer",
    transition: "border-color 0.15s, background 0.15s",
  },
  suggestionIcon: {
    fontSize: 14,
    color: "#9CA3AF",
  },
  citationsPanel: {
    width: 280,
    flexShrink: 0,
    background: "#FFFFFF",
    border: "1px solid #E5E7EB",
    borderRadius: 10,
    overflow: "hidden",
    position: "sticky",
    top: 20,
    maxHeight: "80vh",
    overflowY: "auto",
  },
  citationsHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "12px 14px",
    borderBottom: "1px solid #F3F4F6",
    fontSize: 12,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    color: "#1A1A2E",
    background: "#FAFAFA",
    position: "sticky",
    top: 0,
  },
  closeBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    color: "#9CA3AF",
    fontSize: 14,
    padding: 0,
  },
  citationItem: {
    padding: "12px 14px",
    borderBottom: "1px solid #F9FAFB",
  },
  citationTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 4,
  },
  citationNum: {
    background: "#F3F4F6",
    borderRadius: 4,
    width: 20,
    height: 20,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 700,
    color: "#374151",
    flexShrink: 0,
  },
  citationTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: "#1A1A2E",
    flex: 1,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  citationExcerpt: {
    fontSize: 11,
    color: "#6B7280",
    fontStyle: "italic",
    lineHeight: 1.5,
    margin: "4px 0",
  },
  citationScore: {
    fontSize: 10,
    color: "#9CA3AF",
  },
  emptyState: {
    textAlign: "center",
    padding: "80px 32px",
  },
  emptyIcon: {
    fontSize: 56,
    marginBottom: 16,
    color: "#E5E7EB",
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: "#1A1A2E",
    marginBottom: 8,
  },
  emptySubtitle: {
    fontSize: 14,
    color: "#6B7280",
    lineHeight: 1.7,
    maxWidth: 460,
    margin: "0 auto 32px",
  },
  exampleQueries: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    justifyContent: "center",
    maxWidth: 700,
    margin: "0 auto",
  },
  exampleChip: {
    background: "#FFFFFF",
    border: "1.5px solid #E5E7EB",
    borderRadius: 20,
    padding: "8px 16px",
    fontSize: 13,
    color: "#374151",
    cursor: "pointer",
    textAlign: "left",
  },
};
