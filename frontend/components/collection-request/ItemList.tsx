"use client";

import { useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import { Link as IntlLink } from "@/i18n/routing";
import type { CollectionItem, CollectionItemsResponse } from "@/lib/api";

interface ItemListProps {
  data: CollectionItemsResponse;
  loading: boolean;
  tag: string;
  sort: "rank" | "date";
  order: "asc" | "desc";
  onTagChange: (tag: string) => void;
  onSortChange: (sort: "rank" | "date") => void;
  onOrderChange: (order: "asc" | "desc") => void;
  onPageChange: (page: number) => void;
}

function RelatedItems({ items }: { items: CollectionItem["related_items"] }) {
  const t = useTranslations("collection_requests");
  const [open, setOpen] = useState(false);
  if (!items || items.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition"
      >
        {open ? "▾" : "▸"} {t("related_items", { count: items.length })}
      </button>
      {open && (
        <ul className="mt-1 ml-4 space-y-1">
          {items.map((dup) => (
            <li key={dup.id} className="text-xs text-gray-500 dark:text-gray-400">
              {dup.link ? (
                <IntlLink href={dup.link} className="hover:text-blue-600 dark:hover:text-blue-400 hover:underline">
                  {dup.title || dup.document_id}
                </IntlLink>
              ) : (
                dup.title || "—"
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ItemCard({ item }: { item: CollectionItem }) {
  const t = useTranslations("collection_requests");
  const locale = useLocale();
  const [previewOpen, setPreviewOpen] = useState(false);

  const score =
    item.relevance_score != null ? Math.round(item.relevance_score * 100) : null;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {item.rank_position != null && (
              <span className="text-xs font-mono text-gray-400">#{item.rank_position}</span>
            )}
            <h4 className="text-sm font-semibold text-gray-900 dark:text-white truncate">
              {item.title || t("untitled")}
            </h4>
            {score != null && (
              <span
                title={t("relevance_score")}
                className={`text-xs font-mono px-1.5 py-0.5 rounded-full shrink-0 ${
                  score >= 70
                    ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
                    : score >= 50
                      ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
                }`}
              >
                {score}%
              </span>
            )}
          </div>
          {item.annotation && (
            <p className="mt-1 text-sm text-gray-700 dark:text-gray-300">{item.annotation}</p>
          )}
          {item.snippet && (
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-3">
              {item.snippet}
            </p>
          )}
          {item.category_tags && item.category_tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {item.category_tags.map((tag) => (
                <span
                  key={tag}
                  className="text-[10px] px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 rounded-full"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
            {item.date && <span>{new Date(item.date).toLocaleDateString(locale)}</span>}
            {item.source && <span>{item.source}</span>}
            {item.author && <span>{item.author}</span>}
            {item.status !== "ok" && (
              <span className="text-amber-600 dark:text-amber-400">{item.status}</span>
            )}
          </div>
          <RelatedItems items={item.related_items} />
        </div>
        <div className="flex flex-col items-end gap-2">
          {(item.snippet || item.annotation) && (
            <button
              onClick={() => setPreviewOpen(true)}
              className="text-xs px-2.5 py-1 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition"
            >
              {t("preview")}
            </button>
          )}
          {item.link && (
            <IntlLink
              href={item.link}
              title={t("view_document")}
              className="flex-shrink-0 p-2 text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </IntlLink>
          )}
        </div>
      </div>

      {previewOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={() => setPreviewOpen(false)}
        >
          <div
            className="bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 max-w-2xl w-full max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
              <h4 className="text-sm font-semibold text-gray-900 dark:text-white truncate pr-4">
                {item.title || t("untitled")}
              </h4>
              <button
                onClick={() => setPreviewOpen(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none"
              >
                ×
              </button>
            </div>
            <div className="px-4 py-4 overflow-y-auto space-y-3">
              {item.annotation && (
                <p className="text-sm text-gray-700 dark:text-gray-300">{item.annotation}</p>
              )}
              {item.snippet && (
                <pre className="whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-300 font-sans leading-relaxed">
                  {item.snippet}
                </pre>
              )}
            </div>
            {item.link && (
              <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700">
                <IntlLink
                  href={item.link}
                  onClick={() => setPreviewOpen(false)}
                  className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                >
                  {t("view_document")} →
                </IntlLink>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ItemList({
  data,
  loading,
  tag,
  sort,
  order,
  onTagChange,
  onSortChange,
  onOrderChange,
  onPageChange,
}: ItemListProps) {
  const t = useTranslations("collection_requests");
  const tCommon = useTranslations("common");
  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <input
          type="text"
          value={tag}
          onChange={(e) => onTagChange(e.target.value)}
          placeholder={t("items_filter_tag")}
          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white placeholder-gray-400"
        />
        <select
          value={sort}
          onChange={(e) => onSortChange(e.target.value as "rank" | "date")}
          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
        >
          <option value="rank">{t("items_sort_rank")}</option>
          <option value="date">{t("items_sort_date")}</option>
        </select>
        <select
          value={order}
          onChange={(e) => onOrderChange(e.target.value as "asc" | "desc")}
          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white"
        >
          <option value="asc">{t("order_asc")}</option>
          <option value="desc">{t("order_desc")}</option>
        </select>
      </div>

      {/* Items */}
      {loading ? (
        <div className="text-center py-8">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      ) : data.items.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 py-4">{t("no_items")}</p>
      ) : (
        <div className="space-y-3">
          {data.items.map((item) => (
            <ItemCard key={item.id} item={item} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {data.total > data.page_size && (
        <div className="mt-6 flex justify-center items-center gap-2">
          <button
            onClick={() => onPageChange(Math.max(1, data.page - 1))}
            disabled={data.page === 1}
            className="px-4 py-2 bg-white dark:bg-gray-800 rounded-lg disabled:opacity-50 text-sm"
          >
            {tCommon("previous")}
          </button>
          <span className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">
            {data.page} / {totalPages}
          </span>
          <button
            onClick={() => onPageChange(data.page + 1)}
            disabled={data.page >= totalPages}
            className="px-4 py-2 bg-white dark:bg-gray-800 rounded-lg disabled:opacity-50 text-sm"
          >
            {tCommon("next")}
          </button>
        </div>
      )}
    </div>
  );
}
