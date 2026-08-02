"use client";

import { useTranslations } from "next-intl";
import type { CollectionConfirmation } from "@/lib/api";

interface ConfirmationCardProps {
  confirmation: CollectionConfirmation;
  loading: boolean;
  onConfirm: () => void;
}

function formatParamValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.map(formatParamValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ConfirmationCard({
  confirmation,
  loading,
  onConfirm,
}: ConfirmationCardProps) {
  const t = useTranslations("collection_requests");
  const paramEntries = Object.entries(confirmation.params || {});

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
        {t("confirm_title")}
      </h2>

      {paramEntries.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            {t("confirm_params")}
          </h3>
          <dl className="bg-gray-50 dark:bg-gray-900/50 rounded-lg divide-y divide-gray-200 dark:divide-gray-700">
            {paramEntries.map(([key, value]) => (
              <div key={key} className="px-3 py-2 flex gap-4">
                <dt className="w-40 flex-shrink-0 text-xs font-mono text-gray-500 dark:text-gray-400 truncate">
                  {key}
                </dt>
                <dd className="text-sm text-gray-900 dark:text-white break-words">
                  {formatParamValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {confirmation.analysis_types && confirmation.analysis_types.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            {t("confirm_analysis")}
          </h3>
          <div className="flex flex-wrap gap-2">
            {confirmation.analysis_types.map((type) => (
              <span
                key={type}
                className="text-xs px-2 py-1 bg-purple-100 dark:bg-purple-900/40 text-purple-800 dark:text-purple-200 rounded-full"
              >
                {type}
              </span>
            ))}
          </div>
        </div>
      )}

      {confirmation.assumptions && confirmation.assumptions.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
            {t("confirm_assumptions")}
          </h3>
          <ul className="space-y-1">
            {confirmation.assumptions.map((assumption, idx) => (
              <li
                key={idx}
                className="text-sm text-amber-700 dark:text-amber-300 flex items-start gap-2"
              >
                <span className="mt-0.5">⚠</span>
                <span>{assumption}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-6 flex justify-end">
        <button
          onClick={onConfirm}
          disabled={loading}
          className="px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? t("confirming") : t("confirm_button")}
        </button>
      </div>
    </div>
  );
}
