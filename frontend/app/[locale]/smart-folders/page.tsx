"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations, useLocale } from "next-intl";
import { api } from "@/lib/api";
import { useSmartFolderStream } from "@/hooks/useSmartFolderStream";
import SearchBar from "@/components/smart-folder/SearchBar";
import LoadingState from "@/components/smart-folder/LoadingState";
import ReportViewer from "@/components/smart-folder/ReportViewer";
import CitationPanel from "@/components/smart-folder/CitationPanel";
import RefinementBar from "@/components/smart-folder/RefinementBar";

export const dynamic = "force-dynamic";

interface SmartFolderData {
  id: string;
  name: string;
  query_text: string;
  status: string;
  error_message: string | null;
}

interface ReportData {
  id: string;
  generated_content: {
    title: string;
    summary: string;
    timeline: Array<Record<string, unknown>>;
    patterns: string[];
    trends: string[];
    issues: string[];
    learnings: string[];
    recommendations: string[];
    source_quality?: {
      grade_distribution?: Record<string, number>;
      overall_confidence?: string;
      direct_sources_count?: number;
      contextual_sources_count?: number;
      notes?: string;
    };
    raw_markdown?: string;
  };
  citation_index: Record<string, {
    number: number;
    asset_id: string;
    preview: string;
    document_name?: string;
    page_number?: number | null;
    evidence_grade?: string | null;
    confidence_score?: number | null;
    relation_path?: string | null;
  }>;
  source_asset_ids: string[];
  refinement_query: string | null;
}

export default function SmartFoldersPage() {
  const t = useTranslations("smart_folders");
  const locale = useLocale();

  const [query, setQuery] = useState("");
  const [smartFolder, setSmartFolder] = useState<SmartFolderData | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);
  const [showCitations, setShowCitations] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "error" | "success" } | null>(null);
  const [useFallbackPolling, setUseFallbackPolling] = useState(false);

  // SSE streaming hook
  const {
    loading: streamLoading,
    step: streamStep,
    progressPercent: streamProgress,
    error: streamError,
    result: streamResult,
    startStream,
    cancelStream,
  } = useSmartFolderStream();

  // Handle SSE completion
  useEffect(() => {
    if (streamResult?.smart_folder_id) {
      loadSmartFolder(streamResult.smart_folder_id);
    }
    if (streamError) {
      setError(streamError);
    }
  }, [streamResult, streamError]);

  // Fallback polling state
  const [pollingLoading, setPollingLoading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string | null>(null);

  // Poll for task status (fallback)
  useEffect(() => {
    if (!taskId || !pollingLoading) return;

    const poll = async () => {
      try {
        const res = await api.getGenerationTaskStatus(taskId);
        if (res.error) {
          setError(res.error);
          setPollingLoading(false);
          setTaskId(null);
          return;
        }
        const data = res.data;
        if (!data) return;

        if (data.status === "completed" && data.result) {
          const result = data.result as { smart_folder_id?: string };
          if (result.smart_folder_id) {
            await loadSmartFolder(result.smart_folder_id);
          }
          setPollingLoading(false);
          setTaskId(null);
        } else if (data.status === "failed") {
          setError(data.error || t("generation_failed"));
          setPollingLoading(false);
          setTaskId(null);
        } else {
          setTaskStatus(data.status);
        }
      } catch {
        setError(t("poll_error"));
        setPollingLoading(false);
        setTaskId(null);
      }
    };

    poll();
    const interval = setInterval(poll, 2500);
    return () => clearInterval(interval);
  }, [taskId, pollingLoading, t]);

  const loadSmartFolder = async (id: string) => {
    try {
      const res = await api.getSmartFolder(id);
      if (res.error) {
        setError(res.error);
        return;
      }
      if (res.data) {
        setSmartFolder(res.data.smart_folder);
        if (res.data.latest_report) {
          setReport(res.data.latest_report as ReportData);
        }
      }
    } catch (err) {
      setError(t("load_error"));
    }
  };

  const handleGenerate = useCallback(async (q: string) => {
    setQuery(q);
    setError(null);
    setSmartFolder(null);
    setReport(null);
    setUseFallbackPolling(false);

    if (!useFallbackPolling) {
      // Try SSE first
      startStream(q);
    } else {
      // Fallback to polling
      setPollingLoading(true);
      setTaskId(null);
      try {
        const res = await api.generateSmartFolder(q);
        if (res.error) {
          setError(res.error);
          setPollingLoading(false);
          return;
        }
        if (res.data) {
          setTaskId(res.data.task_id);
        }
      } catch (err) {
        setError(t("generation_failed"));
        setPollingLoading(false);
      }
    }
  }, [startStream, useFallbackPolling, t]);

  const handleRefine = useCallback(async (refinement: string) => {
    if (!smartFolder) return;
    setError(null);

    if (!useFallbackPolling) {
      const combinedQuery = `${smartFolder.query_text} | Refinement: ${refinement}`;
      startStream(combinedQuery);
    } else {
      setPollingLoading(true);
      try {
        const res = await api.refineSmartFolder(smartFolder.id, refinement);
        if (res.error) {
          setError(res.error);
          setPollingLoading(false);
          return;
        }
        if (res.data) {
          setTaskId(res.data.task_id);
        }
      } catch (err) {
        setError(t("refinement_failed"));
        setPollingLoading(false);
      }
    }
  }, [smartFolder, startStream, useFallbackPolling, t]);

  const handleSave = async () => {
    if (!smartFolder) return;
    try {
      const res = await api.saveSmartFolder(smartFolder.id);
      if (res.error) {
        setToast({ message: res.error, type: "error" });
      } else {
        setToast({ message: t("save_success") || "Saved as Note", type: "success" });
      }
    } catch {
      setToast({ message: t("save_error") || "Failed to save", type: "error" });
    }
  };

  const handleCopy = async () => {
    if (!report) return;
    const text = report.generated_content.raw_markdown || JSON.stringify(report.generated_content, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setToast({ message: t("copy_success") || "Copied to clipboard", type: "success" });
    } catch {
      setToast({ message: t("copy_error") || "Failed to copy", type: "error" });
    }
  };

  const handleShare = async () => {
    if (!smartFolder) return;
    const url = `${window.location.origin}/${locale}/smart-folders?id=${smartFolder.id}`;
    try {
      await navigator.clipboard.writeText(url);
      setToast({ message: t("share_success") || "Link copied", type: "success" });
    } catch {
      setToast({ message: t("share_error") || "Failed to copy link", type: "error" });
    }
  };

  const handleRegenerate = async () => {
    if (!smartFolder) return;
    setError(null);
    setReport(null);
    setPollingLoading(true);
    try {
      const response = await api.refreshSmartFolder(smartFolder.id);
      if (response.error) {
        setError(response.error);
        setPollingLoading(false);
        return;
      }
      if (response.data?.task_id) {
        setTaskId(response.data.task_id);
      }
    } catch (exc) {
      setError(t("refresh_error") || "Failed to refresh Smart Folder");
      setPollingLoading(false);
    }
  };

  // Load from URL param on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sfId = params.get("id");
    if (sfId) {
      loadSmartFolder(sfId);
    }
  }, []);

  const loading = streamLoading || pollingLoading;
  const loadingStep = streamLoading ? streamStep : taskStatus || "parsing";

  const examples = [
    "Tell me about my relationship with Bank A",
    "Analyse the balance sheets of my company from 2019 to 2024",
    "Review the NDA with Vendor Y",
    "How did Project Phoenix go?",
    "What are my most important lessons from interacting with John?",
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 shadow">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center gap-4">
            <a
              href={`/${locale}`}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition"
            >
              <svg className="w-6 h-6 text-gray-600 dark:text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              </svg>
            </a>
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">{t("title")}</h1>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{t("subtitle")}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Search Bar */}
        <div className="mb-8">
          <SearchBar onSubmit={handleGenerate} loading={loading} />
        </div>

        {/* Connection mode toggle (dev helper) */}
        <div className="flex justify-end mb-4">
          <button
            onClick={() => setUseFallbackPolling(!useFallbackPolling)}
            className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
          >
            {useFallbackPolling ? "Using polling fallback → switch to SSE" : "Using SSE → switch to polling fallback"}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
            <p className="text-red-800 dark:text-red-200 text-sm">{error}</p>
          </div>
        )}

        {/* Loading */}
        {loading && <LoadingState step={loadingStep} progressPercent={streamProgress} />}

        {/* Report */}
        {!loading && report && smartFolder && (
          <div className="space-y-6">
            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={handleSave}
                className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition"
              >
                {t("save_as_note")}
              </button>
              <button
                onClick={handleCopy}
                className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 text-sm rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition"
              >
                {t("copy")}
              </button>
              <button
                onClick={handleShare}
                className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 text-sm rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition"
              >
                {t("share")}
              </button>
              <button
                onClick={handleRegenerate}
                className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 text-sm rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition"
              >
                {t("regenerate")}
              </button>
            </div>

            {/* Report Viewer */}
            <ReportViewer
              report={report.generated_content}
              citationIndex={report.citation_index}
              onCitationClick={(num) => {
                setActiveCitation(num);
                setShowCitations(true);
              }}
            />

            {/* Refinement */}
            <div className="pt-4">
              <RefinementBar onRefine={handleRefine} loading={loading} />
            </div>
          </div>
        )}

        {/* Empty state examples */}
        {!loading && !report && !error && (
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
            <h3 className="text-sm font-medium text-blue-900 dark:text-blue-200 mb-3">
              {t("examples")}
            </h3>
            <ul className="space-y-2">
              {examples.map((example) => (
                <li key={example}>
                  <button
                    onClick={() => handleGenerate(example)}
                    className="text-sm text-blue-700 dark:text-blue-300 hover:underline text-left"
                  >
                    {`"${example}"`}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Citation Panel */}
      {showCitations && report && (
        <CitationPanel
          citationIndex={report.citation_index}
          activeCitation={activeCitation}
          onClose={() => setShowCitations(false)}
        />
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg ${
            toast.type === "error"
              ? "bg-red-50 dark:bg-red-900 text-red-800 dark:text-red-200 border border-red-200 dark:border-red-800"
              : "bg-green-50 dark:bg-green-900 text-green-800 dark:text-green-200 border border-green-200 dark:border-green-800"
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{toast.message}</span>
            <button onClick={() => setToast(null)} className="ml-2 hover:opacity-70">
              ×
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
