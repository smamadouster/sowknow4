"use client";

import { useEffect, useRef, useState } from "react";

interface VegaLiteChartProps {
  spec: Record<string, unknown>;
  title: string;
}

type VegaEmbedFn = (element: HTMLElement, spec: unknown, opts?: unknown) => Promise<unknown>;

/* eslint-disable */
/** Vega-Embed loaded from CDN to avoid build-time canvas issues. */
function loadVegaEmbed(): Promise<VegaEmbedFn> {
  return new Promise((resolve, reject) => {
    if (typeof window !== "undefined" && (window as any).vegaEmbed) {
      resolve((window as any).vegaEmbed as VegaEmbedFn);
      return;
    }

    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/vega-embed@6.26.0/build/vega-embed.min.js";
    script.async = true;
    script.onload = () => {
      if ((window as any).vegaEmbed) {
        resolve((window as any).vegaEmbed as VegaEmbedFn);
      } else {
        reject(new Error("vega-embed failed to load from CDN"));
      }
    };
    script.onerror = () => reject(new Error("Failed to load vega-embed from CDN"));
    document.head.appendChild(script);
  });
}
/* eslint-enable */

export default function VegaLiteChart({ spec, title }: VegaLiteChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        if (!containerRef.current) return;
        const vegaEmbed = await loadVegaEmbed();
        if (cancelled || !containerRef.current) return;
        await vegaEmbed(containerRef.current, spec, {
          actions: false,
          renderer: "svg",
        });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Chart render error");
        }
      }
    }

    render();

    return () => {
      cancelled = true;
    };
  }, [spec]);

  if (error) {
    return (
      <div className="p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
        <p className="text-sm text-gray-500 dark:text-gray-400">Chart unavailable: {error}</p>
      </div>
    );
  }

  return (
    <div className="p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm">
      <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">{title}</h4>
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
