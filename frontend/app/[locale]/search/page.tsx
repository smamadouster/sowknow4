'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';

interface SearchResult {
  chunk_id: string;
  document_id: string;
  document_name: string;
  document_bucket: string;
  chunk_text: string;
  chunk_index: number;
  page_number: number | null;
  relevance_score: number;
  semantic_score: number;
  keyword_score: number;
}

interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
  llm_used?: string;
  answer?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export default function SearchPage() {
  const t = useTranslations('search');
  const tCommon = useTranslations('common');
  
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [llmUsed, setLlmUsed] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const getToken = (): string | null => {
    if (typeof window === 'undefined') return null;
    const match = document.cookie.match(/access_token=([^;]+)/);
    return match ? match[1] : null;
  };

  const handleSearch = async () => {
    if (!query.trim()) return;

    setLoading(true);
    setHasSearched(true);
    setResults([]);
    setAnswer(null);
    setLlmUsed(null);

    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/v1/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ 
          query: query.trim(),
          limit: 50,
          offset: 0
        }),
      });

      if (res.ok) {
        const data: SearchResponse = await res.json();
        setResults(data.results || []);
        setAnswer(data.answer || null);
        setLlmUsed(data.llm_used || null);
      }
    } catch (e) {
      console.error('Search error:', e);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">{t('title')}</h1>

      {/* Search Input */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
        <div className="flex gap-4">
          <div className="flex-1">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('placeholder')}
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={loading || !query.trim()}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? t('searching') : tCommon('search')}
          </button>
        </div>
      </div>

      {/* LLM Info */}
      {llmUsed && (
        <div className="mb-4 flex items-center gap-2">
          <span className="text-sm text-gray-500">{t('llm_kimi')}:</span>
          <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded text-sm font-medium">
            {llmUsed}
          </span>
        </div>
      )}

      {/* LLM Answer */}
      {answer && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 mb-6">
          <h3 className="font-semibold text-blue-900 mb-2">AI Answer</h3>
          <p className="text-blue-800 whitespace-pre-wrap">{answer}</p>
        </div>
      )}

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <p className="text-gray-600">{t('searching')}</p>
          </div>
        </div>
      ) : hasSearched ? (
        results.length === 0 ? (
          <div className="text-center py-12">
            <svg className="w-16 h-16 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <p className="text-gray-600">{t('no_results')}</p>
          </div>
        ) : (
          <div>
            <p className="text-sm text-gray-500 mb-4">
              {t('found_results', { count: results.length })}
            </p>
            <div className="space-y-4">
              {results.map((result, index) => (
                <div
                  key={result.chunk_id || index}
                  className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="font-semibold text-gray-900">{result.document_name}</h3>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          result.document_bucket === 'confidential' 
                            ? 'bg-orange-100 text-orange-700' 
                            : 'bg-green-100 text-green-700'
                        }`}>
                          {result.document_bucket}
                        </span>
                      </div>
                      <p className="text-gray-600 text-sm line-clamp-3">{result.chunk_text}</p>
                    </div>
                    <div className="ml-4 text-right">
                      <div className="text-lg font-bold text-blue-600">
                        {Math.round(result.relevance_score * 100)}%
                      </div>
                      <p className="text-xs text-gray-400">{t('relevance')}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      ) : (
        <div className="text-center py-12">
          <svg className="w-16 h-16 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <p className="text-gray-600 mb-4">Enter a question to search your documents</p>
          <div className="text-sm text-gray-400">
            Try: "Show me all financial documents from 2023"
          </div>
        </div>
      )}
    </div>
  );
}
