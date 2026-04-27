"use client";

import { useCallback, useRef, useState } from "react";

interface StreamEvent {
  step?: string;
  message?: string;
  progress_percent?: number;
  smart_folder_id?: string;
  report_id?: string;
  report?: Record<string, unknown>;
  error?: string;
}

interface StreamState {
  loading: boolean;
  step: string;
  progressPercent: number;
  error: string | null;
  result: StreamEvent | null;
}

export function useSmartFolderStream() {
  const [state, setState] = useState<StreamState>({
    loading: false,
    step: "parsing",
    progressPercent: 0,
    error: null,
    result: null,
  });

  const abortRef = useRef<AbortController | null>(null);

  const startStream = useCallback((query: string) => {
    setState({
      loading: true,
      step: "parsing",
      progressPercent: 5,
      error: null,
      result: null,
    });

    const abort = new AbortController();
    abortRef.current = abort;

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
    const url = `${apiUrl}/v1/smart-folders/stream`;

    fetch(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ query }),
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
            const event = parseEvent(chunk);
            if (!event) continue;

            if (event.error) {
              setState((s) => ({
                ...s,
                loading: false,
                error: event.error || "Unknown error",
              }));
              return;
            }

            if (event.step) {
              setState((s) => ({
                ...s,
                step: event.step || s.step,
                progressPercent: event.progress_percent || s.progressPercent,
              }));
            }

            if (event.smart_folder_id) {
              setState((s) => ({
                ...s,
                loading: false,
                result: event,
              }));
              return;
            }
          }
        }
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

function parseEvent(chunk: string): StreamEvent | null {
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
    return parsed;
  } catch {
    return null;
  }
}
