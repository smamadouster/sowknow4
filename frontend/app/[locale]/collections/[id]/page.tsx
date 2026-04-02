"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { getCsrfToken } from "@/lib/api";

interface CollectionItem {
  id: string;
  document_id: string;
  article_id?: string;
  article_title?: string;
  article_summary?: string;
  relevance_score: number;
  notes: string | null;
  is_highlighted: boolean;
  document?: {
    id: string;
    filename: string;
    mime_type?: string;
    bucket?: string;
    created_at: string;
  };
}

interface CollectionDetail {
  id: string;
  name: string;
  description: string | null;
  query: string;
  ai_summary: string | null;
  document_count: number;
  is_pinned: boolean;
  is_favorite: boolean;
  created_at: string;
  last_refreshed_at: string | null;
  items: CollectionItem[];
}

export default function CollectionDetailPage() {
  const t = useTranslations();
  const params = useParams();
  const router = useRouter();
  const [collection, setCollection] = useState<CollectionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<Array<{role: string, content: string}>>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [toast, setToast] = useState<{message: string, type: 'error' | 'success'} | null>(null);

  useEffect(() => {
    fetchCollection();
  }, [params.id]);

  const fetchCollection = async () => {
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${params.id}`,
        {
          credentials: 'include',
        }
      );

      if (response.ok) {
        const data: CollectionDetail = await response.json();
        setCollection(data);
      } else if (response.status === 404) {
        setError("Collection not found");
      } else {
        setError("Failed to load collection");
      }
    } catch (err) {
      setError("Error loading collection");
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    if (!collection) return;

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${params.id}/refresh`,
        {
          method: "POST",
          headers: { "X-CSRF-Token": getCsrfToken() },
          credentials: "include",
        }
      );

      if (response.ok) {
        fetchCollection();
      }
    } catch (error) {
      console.error("Error refreshing collection:", error);
    }
  };

  const handleExportPdf = async () => {
    if (!collection) return;

    setExportLoading(true);
    setToast(null);

    try {
      const locale = params.locale || 'en';
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/v1/smart-folders/reports/generate`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": getCsrfToken(),
          },
          body: JSON.stringify({
            collection_id: collection.id,
            format: "standard",
            language: locale,
            include_citations: true,
          }),
        }
      );

      if (response.ok) {
        const data = await response.json();
        
        if (data.content) {
          setToast({ message: t('collections.export_success'), type: 'success' });
          
          const filename = `${collection.name.replace(/[^a-z0-9]/gi, '_')}_report.md`;
          const blob = new Blob([data.content], { type: 'text/markdown' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }
      } else {
        const errorData = await response.json();
        setToast({ message: errorData.detail || t('collections.export_error'), type: 'error' });
      }
    } catch (error) {
      console.error("Error exporting PDF:", error);
      setToast({ message: t('collections.export_error'), type: 'error' });
    } finally {
      setExportLoading(false);
      setTimeout(() => setToast(null), 5000);
    }
  };

  const handleChat = async () => {
    if (!chatInput.trim() || !collection) return;

    const userMessage = chatInput;
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setChatLoading(true);

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${params.id}/chat`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": getCsrfToken(),
          },
          body: JSON.stringify({
            message: userMessage,
          }),
        }
      );

      if (response.ok) {
        const data = await response.json();
        setChatMessages((prev) => [...prev, { role: "assistant", content: data.response }]);
      }
    } catch (error) {
      console.error("Error sending chat message:", error);
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, I couldn't process that message." },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
        <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error || !collection) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 dark:text-red-400">{error || "Collection not found"}</p>
          <button
            onClick={() => router.back()}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.back()}
              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
            >
              ← {t("common.back")}
            </button>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                {collection.is_pinned && <span>📌</span>}
                {collection.is_favorite && <span>❤️</span>}
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                  {collection.name}
                </h1>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                {collection.document_count} documents • Created{" "}
                {new Date(collection.created_at).toLocaleDateString()}
              </p>
            </div>
            <button
              onClick={handleRefresh}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
            >
              Refresh
            </button>
            <button
              onClick={handleExportPdf}
              disabled={exportLoading || collection.items.length === 0}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {exportLoading ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  {t('collections.exporting_pdf')}
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  {t('collections.export_pdf')}
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Toast Notification */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg ${
          toast.type === 'error' 
            ? 'bg-red-50 dark:bg-red-900 text-red-800 dark:text-red-200 border border-red-200 dark:border-red-800'
            : 'bg-green-50 dark:bg-green-900 text-green-800 dark:text-green-200 border border-green-200 dark:border-green-800'
        }`}>
          <div className="flex items-center gap-2">
            {toast.type === 'error' ? (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            ) : (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
            <span className="text-sm font-medium">{toast.message}</span>
            <button
              onClick={() => setToast(null)}
              className="ml-2 hover:opacity-70"
            >
              ×
            </button>
          </div>
        </div>
      )}

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Main Content - Documents */}
          <div className="lg:col-span-2">
            {/* Query & Summary */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mb-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Query
              </h2>
              <p className="text-gray-700 dark:text-gray-300 mb-4">{collection.query}</p>

              {collection.ai_summary && (
                <>
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                    AI Summary
                  </h2>
                  <p className="text-gray-700 dark:text-gray-300">{collection.ai_summary}</p>
                </>
              )}
            </div>

            {/* Documents List */}
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
              <div className="p-6 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Documents ({collection.items.length})
                </h2>
              </div>
              <div className="divide-y divide-gray-200 dark:divide-gray-700">
                {collection.items.map((item) => (
                  <div
                    key={item.id}
                    className={`p-4 hover:bg-gray-50 dark:hover:bg-gray-700 transition ${
                      item.is_highlighted ? "bg-yellow-50 dark:bg-yellow-900/20" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          {item.is_highlighted && <span>⭐</span>}
                          <h3 className="font-medium text-gray-900 dark:text-white truncate">
                            {item.article_title || item.document?.filename || "Unknown Document"}
                          </h3>
                          {item.document?.bucket === "confidential" && (
                            <span className="text-xs px-2 py-1 bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200 rounded flex-shrink-0">
                              Confidential
                            </span>
                          )}
                        </div>
                        {item.article_summary && (
                          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 line-clamp-2">
                            {item.article_summary}
                          </p>
                        )}
                        {!item.article_summary && item.notes && (
                          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                            {item.notes}
                          </p>
                        )}
                        {item.article_title && item.document?.filename && (
                          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                            {item.document.filename}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          {item.relevance_score}%
                        </span>
                        {item.document && (
                          <div className="flex gap-1">
                            <a
                              href={`/${params.locale}/documents/${item.document.id}`}
                              className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded"
                              title={t('collections.preview')}
                            >
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                              </svg>
                            </a>
                            <a
                              href={`${process.env.NEXT_PUBLIC_API_URL}/api/v1/documents/${item.document.id}/download`}
                              className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded"
                              title={t('collections.download')}
                            >
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                            </a>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Sidebar - Chat */}
          <div className="lg:col-span-1">
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow sticky top-6">
              <div className="p-4 border-b border-gray-200 dark:border-gray-700">
                <h2 className="font-semibold text-gray-900 dark:text-white">
                  Ask about this collection
                </h2>
              </div>
              <div className="p-4 h-96 overflow-y-auto">
                {chatMessages.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-8">
                    Ask a question about the documents in this collection
                  </p>
                ) : (
                  <div className="space-y-4">
                    {chatMessages.map((msg, idx) => (
                      <div
                        key={idx}
                        className={`${
                          msg.role === "user" ? "text-right" : "text-left"
                        }`}
                      >
                        <span
                          className={`inline-block px-3 py-2 rounded-lg text-sm ${
                            msg.role === "user"
                              ? "bg-blue-600 text-white"
                              : "bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white"
                          }`}
                        >
                          {msg.content}
                        </span>
                      </div>
                    ))}
                    {chatLoading && (
                      <div className="text-left">
                        <span className="inline-block px-3 py-2 rounded-lg text-sm bg-gray-100 dark:bg-gray-700">
                          Thinking...
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
              <div className="p-4 border-t border-gray-200 dark:border-gray-700">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyPress={(e) => e.key === "Enter" && handleChat()}
                    placeholder="Ask a question..."
                    className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white text-sm"
                  />
                  <button
                    onClick={handleChat}
                    disabled={chatLoading || !chatInput.trim()}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
                  >
                    Send
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
