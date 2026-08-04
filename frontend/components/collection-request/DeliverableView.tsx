"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslations } from "next-intl";
import ChartRenderer from "@/components/smart-folder/ChartRenderer";
import { getCsrfToken } from "@/lib/api";
import { showToast } from "@/lib/toast";
import type {
  CollectionAppendixEntry,
  CollectionAppendixTable,
  CollectionDeliverableView,
  CollectionDisclosure,
} from "@/lib/api";

interface DeliverableViewProps {
  view: CollectionDeliverableView;
}

function disclosureText(disclosure: CollectionDisclosure): string {
  if (typeof disclosure.message === "string" && disclosure.message) {
    return disclosure.message;
  }
  const parts = Object.entries(disclosure)
    .filter(([key]) => key !== "type")
    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`);
  return parts.join(", ");
}

function AppendixTableView({ table }: { table: CollectionAppendixTable }) {
  return (
    <div className="overflow-x-auto">
      <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">{table.title}</h4>
      <table className="min-w-full text-sm border border-gray-200 dark:border-gray-700 rounded-lg">
        <thead>
          <tr className="bg-gray-50 dark:bg-gray-900/50">
            {table.columns.map((col) => (
              <th
                key={col}
                className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {table.rows.map((row, idx) => (
            <tr key={idx}>
              {table.columns.map((col) => (
                <td key={col} className="px-3 py-2 text-gray-700 dark:text-gray-300">
                  {row[col] === null || row[col] === undefined ? "—" : String(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AppendixEntryView({ entry }: { entry: CollectionAppendixEntry }) {
  return (
    <div className="space-y-4">
      {entry.analysis_type && (
        <span className="text-xs px-2 py-1 bg-purple-100 dark:bg-purple-900/40 text-purple-800 dark:text-purple-200 rounded-full">
          {entry.analysis_type}
        </span>
      )}
      {entry.messages?.map((message, idx) => (
        <p key={idx} className="text-sm text-gray-500 dark:text-gray-400 italic">
          {message}
        </p>
      ))}
      {entry.tables?.map((table, idx) => (
        <AppendixTableView key={idx} table={table} />
      ))}
      {entry.charts?.map((spec, idx) => (
        <ChartRenderer
          key={idx}
          visualisation={{
            type: "chart",
            title: (spec.title as string) || "Chart",
            spec,
            chart_type: "vega-lite",
          }}
        />
      ))}
    </div>
  );
}

export default function DeliverableView({ view }: DeliverableViewProps) {
  const t = useTranslations("collection_requests");
  const [exporting, setExporting] = useState(false);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
  const requestId = view.request_id;
  const isZeroResult =
    view.appendix?.outcome === "zero_results" ||
    (!view.summary_md && view.items.length === 0);

  const handleExportZip = async () => {
    setExporting(true);
    try {
      const response = await fetch(
        `${apiUrl}/v1/collection-requests/${requestId}/deliverable/export?format=zip`,
        { credentials: "include", headers: { "X-CSRF-Token": getCsrfToken() } }
      );
      if (!response.ok) {
        throw new Error(`Export failed (${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `sowknow_collection_${requestId}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err instanceof Error ? err.message : t("export_failed"), "error");
    } finally {
      setExporting(false);
    }
  };

  const handleExportPdf = async () => {
    setExporting(true);
    try {
      const response = await fetch(
        `${apiUrl}/v1/collection-requests/${requestId}/deliverable/export?format=pdf`,
        { credentials: "include", headers: { "X-CSRF-Token": getCsrfToken() } }
      );
      if (!response.ok) {
        throw new Error(`Export failed (${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `sowknow_collection_${requestId}.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(err instanceof Error ? err.message : t("export_failed"), "error");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={handleExportPdf}
          disabled={exporting}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition disabled:opacity-50"
        >
          {exporting ? t("exporting") : t("export_pdf")}
        </button>
        <button
          onClick={handleExportZip}
          disabled={exporting}
          className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 transition disabled:opacity-50"
        >
          {exporting ? t("exporting") : t("export_zip")}
        </button>
        <a
          href={`${apiUrl}/v1/collection-requests/${requestId}/audit?format=json`}
          target="_blank"
          rel="noopener noreferrer"
          className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 text-sm rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition"
        >
          {t("export_audit_json")}
        </a>
        <a
          href={`${apiUrl}/v1/collection-requests/${requestId}/audit?format=csv`}
          className="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 text-sm rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition"
        >
          {t("export_audit_csv")}
        </a>
      </div>

      {/* Disclosures */}
      {view.disclosures && view.disclosures.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 space-y-1">
          {view.disclosures.map((disclosure, idx) => (
            <p
              key={idx}
              className="text-sm text-amber-800 dark:text-amber-200 flex items-start gap-2"
            >
              <span className="mt-0.5 shrink-0">⚠</span>
              <span>
                {disclosure.type && (
                  <strong className="font-medium mr-1">{disclosure.type}:</strong>
                )}
                {disclosureText(disclosure)}
              </span>
            </p>
          ))}
        </div>
      )}

      {/* Zero-result state */}
      {isZeroResult ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            {t("zero_title")}
          </h3>

          {view.appendix?.executed_queries && view.appendix.executed_queries.length > 0 && (
            <div className="mb-4">
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                {t("zero_executed_queries")}
              </h4>
              <div className="space-y-2">
                {view.appendix.executed_queries.map((query, idx) => (
                  <pre
                    key={idx}
                    className="text-xs bg-gray-50 dark:bg-gray-900/50 text-gray-600 dark:text-gray-400 rounded-lg p-3 overflow-x-auto"
                  >
                    {JSON.stringify(query, null, 2)}
                  </pre>
                ))}
              </div>
            </div>
          )}

          {view.appendix?.relaxation_suggestions &&
            view.appendix.relaxation_suggestions.length > 0 && (
              <div>
                <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  {t("zero_suggestions")}
                </h4>
                <ul className="space-y-1">
                  {view.appendix.relaxation_suggestions.map((suggestion, idx) => (
                    <li
                      key={idx}
                      className="text-sm text-gray-600 dark:text-gray-400 flex items-start gap-2"
                    >
                      <span className="text-blue-600 mt-0.5">•</span>
                      {suggestion}
                    </li>
                  ))}
                </ul>
              </div>
            )}
        </div>
      ) : (
        view.summary_md && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              {t("result_summary")}
            </h3>
            <div className="prose dark:prose-invert max-w-none text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
              <ReactMarkdown>{view.summary_md}</ReactMarkdown>
            </div>
          </div>
        )
      )}

      {/* Appendix: analysis tables + charts */}
      {view.appendix?.analyses_rendered && view.appendix.analyses_rendered.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            {t("result_appendix")}
          </h3>
          <div className="space-y-6">
            {view.appendix.analyses_rendered.map((entry, idx) => (
              <AppendixEntryView key={idx} entry={entry} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
