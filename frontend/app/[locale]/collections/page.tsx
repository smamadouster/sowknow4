"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useTranslations, useLocale } from "next-intl";
import { Link as IntlLink } from "@/i18n/routing";

// Disable static optimization for this client component
export const dynamic = 'force-dynamic';

interface Collection {
  id: string;
  name: string;
  description: string | null;
  collection_type: string;
  visibility: string;
  query: string;
  ai_summary: string | null;
  document_count: number;
  is_pinned: boolean;
  is_favorite: boolean;
  created_at: string;
}

interface CollectionsResponse {
  collections: Collection[];
  total: number;
  page: number;
  page_size: number;
}

export default function CollectionsPage() {
  const t = useTranslations('collections');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newQuery, setNewQuery] = useState("");

  useEffect(() => {
    fetchCollections();
  }, [page]);

  const fetchCollections = async () => {
    try {
      const { api } = await import("@/lib/api");
      const response = await api.getCollections(page, 20);

      if (response.data && !response.error) {
        const data: CollectionsResponse = response.data as CollectionsResponse;
        setCollections(data.collections);
        setTotal(data.total);
      }
    } catch (error) {
      console.error("Error fetching collections:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateCollection = async () => {
    if (!newQuery.trim()) return;

    try {
      const { api } = await import("@/lib/api");
      const response = await api.createCollection(
        newQuery.slice(0, 50),
        newQuery
      );

      if (response.data && !response.error) {
        setShowCreateModal(false);
        setNewQuery("");
        fetchCollections();
      }
    } catch (error) {
      console.error("Error creating collection:", error);
    }
  };

  const togglePin = async (collectionId: string) => {
    try {
      const { api } = await import("@/lib/api");
      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${collectionId}/pin`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
      fetchCollections();
    } catch (error) {
      console.error("Error toggling pin:", error);
    }
  };

  const toggleFavorite = async (collectionId: string) => {
    try {
      const { api } = await import("@/lib/api");
      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${collectionId}/favorite`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
      fetchCollections();
    } catch (error) {
      console.error("Error toggling favorite:", error);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
                {t('title')}
              </h1>
              <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                {t('create_from_query')}
              </p>
            </div>
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
            >
              {t('create')}
            </button>
          </div>
        </div>
      </div>

      {/* Collections Grid */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {loading ? (
          <div className="text-center py-12">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
            <p className="mt-4 text-gray-600 dark:text-gray-400">
              {tCommon('loading')}
            </p>
          </div>
        ) : collections.length === 0 ? (
          <div className="text-center py-12">
            <svg
              className="mx-auto h-12 w-12 text-gray-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
              />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
              {t('no_collections')}
            </h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {t('no_collections_desc')}
            </p>
            <div className="mt-6">
              <button
                onClick={() => setShowCreateModal(true)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
              >
                {t('create')}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {collections.map((collection) => (
                <IntlLink
                  key={collection.id}
                  href={`/collections/${collection.id}`}
                  className="block"
                >
                  <div className="bg-white dark:bg-gray-800 rounded-lg shadow hover:shadow-lg transition p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          {collection.is_pinned && (
                            <span className="text-yellow-500" title={t('pin')}>
                              📌
                            </span>
                          )}
                          {collection.is_favorite && (
                            <span className="text-red-500" title={t('favorite')}>
                              ❤️
                            </span>
                          )}
                          <h3 className="text-lg font-semibold text-gray-900 dark:text-white truncate">
                            {collection.name}
                          </h3>
                        </div>
                        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
                          {collection.ai_summary || collection.query}
                        </p>
                      </div>
                    </div>

                    <div className="mt-4 flex items-center justify-between">
                      <span className="text-sm text-gray-500 dark:text-gray-400">
                        {collection.document_count} {t('documents')}
                      </span>
                      <span className="text-xs px-2 py-1 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded">
                        {collection.collection_type}
                      </span>
                    </div>

                    <div className="mt-3 text-xs text-gray-400 dark:text-gray-500">
                      {new Date(collection.created_at).toLocaleDateString(locale)}
                    </div>

                    {/* Action buttons */}
                    <div className="mt-4 flex gap-2">
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          togglePin(collection.id);
                        }}
                        className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                        title={collection.is_pinned ? t('unpin') : t('pin')}
                      >
                        📌
                      </button>
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          toggleFavorite(collection.id);
                        }}
                        className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                        title={collection.is_favorite ? t('unfavorite') : t('favorite')}
                      >
                        ❤️
                      </button>
                    </div>
                  </div>
                </IntlLink>
              ))}
            </div>

            {/* Pagination */}
            {total > 20 && (
              <div className="mt-8 flex justify-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-4 py-2 bg-white dark:bg-gray-800 rounded-lg disabled:opacity-50"
                >
                  {tCommon('previous')}
                </button>
                <span className="px-4 py-2 text-gray-600 dark:text-gray-400">
                  {tCommon('next')} {page}
                </span>
                <button
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page * 20 >= total}
                  className="px-4 py-2 bg-white dark:bg-gray-800 rounded-lg disabled:opacity-50"
                >
                  {tCommon('next')}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Create Collection Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              {t('new_collection')}
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              {t('create_from_query')}. {t('examples')}:
            </p>
            <ul className="text-sm text-gray-600 dark:text-gray-400 mb-4 list-disc list-inside">
              <li>{t('example_1')}</li>
              <li>{t('example_2')}</li>
              <li>{t('example_3')}</li>
            </ul>

            <textarea
              value={newQuery}
              onChange={(e) => setNewQuery(e.target.value)}
              placeholder={t('query_placeholder')}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
              rows={3}
            />

            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  setNewQuery("");
                }}
                className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleCreateCollection}
                disabled={!newQuery.trim()}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('create')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
