"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

interface CollectionItem {
  id: string;
  document_id: string;
  relevance_score: number;
  notes: string | null;
  is_highlighted: boolean;
  document?: {
    id: string;
    filename: string;
    bucket: string;
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

  useEffect(() => {
    fetchCollection();
  }, [params.id]);

  const fetchCollection = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${params.id}`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
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
      const token = localStorage.getItem("token");
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${params.id}/refresh`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (response.ok) {
        fetchCollection();
      }
    } catch (error) {
      console.error("Error refreshing collection:", error);
    }
  };

  const handleChat = async () => {
    if (!chatInput.trim() || !collection) return;

    const userMessage = chatInput;
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setChatLoading(true);

    try {
      const token = localStorage.getItem("token");
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/collections/${params.id}/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
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
          </div>
        </div>
      </div>

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
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          {item.is_highlighted && <span>⭐</span>}
                          <h3 className="font-medium text-gray-900 dark:text-white">
                            {item.document?.filename || "Unknown Document"}
                          </h3>
                          {item.document?.bucket === "confidential" && (
                            <span className="text-xs px-2 py-1 bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200 rounded">
                              Confidential
                            </span>
                          )}
                        </div>
                        {item.notes && (
                          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                            {item.notes}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-gray-500 dark:text-gray-400">
                          {item.relevance_score}% relevant
                        </span>
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
