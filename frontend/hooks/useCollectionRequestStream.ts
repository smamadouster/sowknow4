"use client";

import { useCallback, useRef, useState } from "react";

interface StreamEvent {
  step?: string;
  message?: string;
  progress_percent?: number;
  request_id?: string;
  deliverable_id?: string | null;
  error?: string;
}

interface StreamState {
  loading: boolean;
  step: string;
  message: string | null;
  progressPercent: number;
  error: string | null;
  deliverableId: string | null;
  finished: boolean;
  timedOut: boolean;
}

export function useCollectionRequestStream() {
  const [state, setState] = useState<StreamState>({
    loading: false,
    step: "queued",
    message: null,
    progressPercent: 0,
    error: null,
    deliverableId: null,
    finished: false,
    timedOut: false,
  });

  const abortRef = useRef<AbortController | null>(null);

  const startStream = useCallback((requestId: string) => {
    setState({
      loading: true,
      step: "queued",
      message: null,
      progressPercent: 5,
      error: null,
      deliverableId: null,
      finished: false,
      timedOut: false,
    });

    const abort = new AbortController();
    abortRef.current = abort;

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
    const url = `${apiUrl}/v1/collection-requests/${requestId}/stream`;

    fetch(url, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "text/event-stream" },
      signal: abort.signal,
    })
      .then(async (response) => {
        if (!response.ok || !response.body) {
          const text = await response.text();
          throw new Error(text || "Stream failed");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const chunk of lines) {
            const parsed = parseEvent(chunk);
            if (!parsed) continue;
            const { eventName, event } = parsed;

            if (eventName === "error" || event.error) {
              setState((s) => ({
                ...s,
                loading: false,
                error: event.error || "Unknown error",
              }));
              return;
            }

            if (eventName === "complete") {
              setState((s) => ({
                ...s,
                loading: false,
                progressPercent: 100,
                deliverableId: event.deliverable_id || null,
                finished: true,
              }));
              return;
            }

            if (event.step === "timeout") {
              // Server-side SSE window expired; caller should poll /status.
              setState((s) => ({
                ...s,
                loading: false,
                timedOut: true,
                message: event.message || s.message,
              }));
              return;
            }

            if (event.step) {
              setState((s) => ({
                ...s,
                step: event.step || s.step,
                message: event.message || s.message,
                progressPercent: event.progress_percent || s.progressPercent,
              }));
            }
          }
        }

        // Stream closed without complete/error — treat as timeout so the
        // caller falls back to polling.
        setState((s) => (s.loading ? { ...s, loading: false, timedOut: true } : s));
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setState((s) => ({
          ...s,
          loading: false,
          error: err.message || "Stream error",
        }));
      });

    return () => {
      abort.abort();
    };
  }, []);

  const cancelStream = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => ({ ...s, loading: false }));
  }, []);

  return { ...state, startStream, cancelStream };
}

function parseEvent(chunk: string): { eventName: string; event: StreamEvent } | null {
  const lines = chunk.split("\n");
  let data = "";
  let eventName = "";

  for (const line of lines) {
    if (line.startsWith("data: ")) {
      data = line.slice(6);
    } else if (line.startsWith("event: ")) {
      eventName = line.slice(7);
    }
  }

  if (!data) return null;

  try {
    const parsed = JSON.parse(data) as StreamEvent;
    return { eventName, event: parsed };
  } catch {
    return null;
  }
}
