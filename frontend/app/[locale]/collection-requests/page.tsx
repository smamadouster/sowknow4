"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Link as IntlLink } from "@/i18n/routing";
import { api } from "@/lib/api";
import type {
  CollectionClarificationQuestion,
  CollectionConfirmation,
  CollectionDeliverableView,
  CollectionItemsResponse,
} from "@/lib/api";
import { useCollectionRequestStream } from "@/hooks/useCollectionRequestStream";
import { useDebounce } from "@/hooks/useDebounce";
import SearchBar from "@/components/smart-folder/SearchBar";
import ClarificationDialog from "@/components/collection-request/ClarificationDialog";
import ConfirmationCard from "@/components/collection-request/ConfirmationCard";
import CollectionProgress from "@/components/collection-request/CollectionProgress";
import DeliverableView from "@/components/collection-request/DeliverableView";
import ItemList from "@/components/collection-request/ItemList";

export const dynamic = "force-dynamic";

type Phase =
  | "input"
  | "clarifying"
  | "confirming"
  | "processing"
  | "result"
  | "failed";

const POLLABLE_STATES = new Set([
  "queued",
  "searching",
  "processing",
  "analysing",
  "summarising",
  "packaging",
]);

export default function CollectionRequestsPage() {
  const t = useTranslations("collection_requests");
  const tCommon = useTranslations("common");
  const locale = useLocale();

  const [phase, setPhase] = useState<Phase>("input");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Clarification state
  const [questions, setQuestions] = useState<CollectionClarificationQuestion[]>([]);
  const [round, setRound] = useState(1);
  const [maxRounds, setMaxRounds] = useState(3);
  const [confirmation, setConfirmation] = useState<CollectionConfirmation | null>(null);

  // Result state
  const [deliverable, setDeliverable] = useState<CollectionDeliverableView | null>(null);
  const [itemsData, setItemsData] = useState<CollectionItemsResponse>({
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
  });
  const [itemsLoading, setItemsLoading] = useState(false);
  const [itemTag, setItemTag] = useState("");
  const [itemSort, setItemSort] = useState<"rank" | "date">("rank");
  const [itemOrder, setItemOrder] = useState<"asc" | "desc">("asc");
  const [itemPage, setItemPage] = useState(1);
  const debouncedTag = useDebounce(itemTag, 400);

  // Polling fallback
  const [polling, setPolling] = useState(false);
  const [polledStep, setPolledStep] = useState<string>("queued");

  const {
    loading: streamLoading,
    step: streamStep,
    message: streamMessage,
    progressPercent: streamProgress,
    error: streamError,
    finished: streamFinished,
    timedOut: streamTimedOut,
    startStream,
  } = useCollectionRequestStream();

  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());

  const resetAll = useCallback(() => {
    setPhase("input");
    setRequestId(null);
    setSubmitting(false);
    setError(null);
    setNotice(null);
    setQuestions([]);
    setRound(1);
    setConfirmation(null);
    setDeliverable(null);
    setItemsData({ items: [], total: 0, page: 1, page_size: 20 });
    setItemTag("");
    setItemSort("rank");
    setItemOrder("asc");
    setItemPage(1);
    setPolling(false);
    setPolledStep("queued");
    idempotencyKeyRef.current = crypto.randomUUID();
  }, []);

  const loadResult = useCallback(
    async (id: string) => {
      const res = await api.getCollectionDeliverable(id);
      if (res.error || !res.data) {
        setError(res.error || t("load_error"));
        setPhase("failed");
        return;
      }
      setDeliverable(res.data);
      setPhase("result");
    },
    [t]
  );

  const startProcessing = useCallback(
    (id: string) => {
      setPhase("processing");
      setPolling(false);
      startStream(id);
    },
    [startStream]
  );

  // --- Create request + start clarification ---
  const handleSubmitQuery = async (query: string) => {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.createCollectionRequest(query, idempotencyKeyRef.current);
      if (res.error || !res.data) {
        setError(res.error || t("create_failed"));
        return;
      }
      const { request_id, clarification } = res.data;
      setRequestId(request_id);
      setRound(clarification.round);
      setMaxRounds(clarification.max_rounds);

      if (!clarification.questions || clarification.questions.length === 0) {
        // No ambiguity: jump straight to the confirmation payload.
        const step = await api.clarifyCollectionRequest(request_id, {}, true);
        if (step.error || !step.data) {
          setError(step.error || t("clarify_failed"));
          return;
        }
        if (step.data.ready_to_confirm && step.data.confirmation) {
          setConfirmation(step.data.confirmation);
          setPhase("confirming");
          return;
        }
        setQuestions(step.data.questions || []);
        setRound(step.data.round);
        setMaxRounds(step.data.max_rounds);
        setPhase("clarifying");
        return;
      }

      setQuestions(clarification.questions);
      setPhase("clarifying");
    } catch {
      setError(t("create_failed"));
    } finally {
      setSubmitting(false);
    }
  };

  // --- Answer a clarification round (or skip) ---
  const handleClarify = async (answers: Record<string, string>, skip: boolean) => {
    if (!requestId) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.clarifyCollectionRequest(requestId, answers, skip);
      if (res.error || !res.data) {
        setError(res.error || t("clarify_failed"));
        return;
      }
      if (res.data.ready_to_confirm && res.data.confirmation) {
        setConfirmation(res.data.confirmation);
        setPhase("confirming");
        return;
      }
      setQuestions(res.data.questions || []);
      setRound(res.data.round);
      setMaxRounds(res.data.max_rounds);
    } catch {
      setError(t("clarify_failed"));
    } finally {
      setSubmitting(false);
    }
  };

  // --- Confirm params + enqueue ---
  const handleConfirm = async () => {
    if (!requestId) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.confirmCollectionRequest(requestId);
      if (res.error) {
        setError(res.error);
        return;
      }
      startProcessing(requestId);
    } catch {
      setError(t("confirm_failed"));
    } finally {
      setSubmitting(false);
    }
  };

  // --- SSE completion / failure handling ---
  useEffect(() => {
    if (streamFinished && requestId) {
      loadResult(requestId);
    }
  }, [streamFinished, requestId, loadResult]);

  useEffect(() => {
    // On stream failure or server-side timeout, fall back to polling /status.
    if ((streamError || streamTimedOut) && phase === "processing" && requestId) {
      setPolling(true);
    }
  }, [streamError, streamTimedOut, phase, requestId]);

  // --- Polling fallback ---
  useEffect(() => {
    if (!polling || !requestId || phase !== "processing") return;

    const poll = async () => {
      const res = await api.getCollectionRequestStatus(requestId);
      if (res.error || !res.data) return;
      const state = res.data.job_state || "";
      if (state === "completed") {
        setPolling(false);
        await loadResult(requestId);
      } else if (state === "failed" || state === "cancelled") {
        setPolling(false);
        setError(res.data.error_message || t("job_failed"));
        setPhase("failed");
      } else if (POLLABLE_STATES.has(state)) {
        setPolledStep(state);
      }
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [polling, requestId, phase, loadResult, t]);

  // --- Items fetching (result phase, with filters) ---
  useEffect(() => {
    if (phase !== "result" || !requestId) return;
    let cancelled = false;

    const fetchItems = async () => {
      setItemsLoading(true);
      const res = await api.getCollectionRequestItems(requestId, {
        tag: debouncedTag || undefined,
        sort: itemSort,
        order: itemOrder,
        page: itemPage,
        pageSize: 20,
      });
      if (!cancelled) {
        if (res.data) setItemsData(res.data);
        setItemsLoading(false);
      }
    };

    fetchItems();
    return () => {
      cancelled = true;
    };
  }, [phase, requestId, debouncedTag, itemSort, itemOrder, itemPage]);

  // --- Resume from ?id= URL param ---
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    if (!id) return;

    const resume = async () => {
      const res = await api.getCollectionRequestStatus(id);
      if (res.error || !res.data) {
        setError(res.error || t("load_error"));
        return;
      }
      setRequestId(id);
      const state = res.data.job_state || "";
      if (state === "completed") {
        await loadResult(id);
      } else if (POLLABLE_STATES.has(state)) {
        startProcessing(id);
      } else if (state === "failed" || state === "cancelled") {
        setError(res.data.error_message || t("job_failed"));
        setPhase("failed");
      } else {
        // draft / clarifying — no GET endpoint for the open session.
        setNotice(t("resume_unavailable"));
      }
    };
    resume();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const displayStep = polling ? polledStep : streamStep;
  const processing = phase === "processing";

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 shadow">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center gap-4">
            <IntlLink
              href="/"
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition"
              title={tCommon("home")}
            >
              <svg className="w-6 h-6 text-gray-600 dark:text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              </svg>
            </IntlLink>
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
                {t("title")}
              </h1>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                {t("subtitle")}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Query input */}
        {(phase === "input" || phase === "failed") && (
          <div className="mb-8">
            <SearchBar
              onSubmit={handleSubmitQuery}
              loading={submitting}
              placeholder={t("search_placeholder")}
            />
          </div>
        )}

        {/* New request shortcut once a flow is underway */}
        {phase !== "input" && (
          <div className="flex justify-end mb-4">
            <button
              onClick={resetAll}
              className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
            >
              {t("new_request")}
            </button>
          </div>
        )}

        {/* Notice (e.g. unresumable clarification session) */}
        {notice && (
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
            <p className="text-blue-800 dark:text-blue-200 text-sm">{notice}</p>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
            <p className="text-red-800 dark:text-red-200 text-sm font-medium">
              {t("failed_title")}
            </p>
            <p className="text-red-700 dark:text-red-300 text-sm mt-1">{error}</p>
          </div>
        )}

        {/* Clarification dialogue */}
        {phase === "clarifying" && (
          <ClarificationDialog
            questions={questions}
            round={round}
            maxRounds={maxRounds}
            loading={submitting}
            onSubmit={(answers) => handleClarify(answers, false)}
            onSkip={() => handleClarify({}, true)}
          />
        )}

        {/* Confirmation */}
        {phase === "confirming" && confirmation && (
          <ConfirmationCard
            confirmation={confirmation}
            loading={submitting}
            onConfirm={handleConfirm}
          />
        )}

        {/* Live progress */}
        {processing && (
          <CollectionProgress
            step={displayStep}
            message={streamMessage}
            progressPercent={polling ? 0 : streamProgress}
          />
        )}

        {/* Result */}
        {phase === "result" && deliverable && (
          <div className="space-y-8">
            <DeliverableView view={deliverable} />
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                {t("result_items")}
              </h3>
              <ItemList
                data={itemsData}
                loading={itemsLoading}
                tag={itemTag}
                sort={itemSort}
                order={itemOrder}
                onTagChange={(tag) => {
                  setItemTag(tag);
                  setItemPage(1);
                }}
                onSortChange={(sort) => {
                  setItemSort(sort);
                  setItemPage(1);
                }}
                onOrderChange={(order) => {
                  setItemOrder(order);
                  setItemPage(1);
                }}
                onPageChange={setItemPage}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
