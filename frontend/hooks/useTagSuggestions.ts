'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export interface TagSuggestion {
  tag_name: string;
  count: number;
}

interface UseTagSuggestionsResult {
  suggestions: TagSuggestion[];
  topTags: TagSuggestion[];
  loading: boolean;
}

export function useTagSuggestions(query: string, limit = 8): UseTagSuggestionsResult {
  const [suggestions, setSuggestions] = useState<TagSuggestion[]>([]);
  const [topTags, setTopTags] = useState<TagSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch top tags on mount (no query)
  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/v1/tags/suggestions?limit=${limit}`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : { tags: [] })
      .then(data => {
        if (!cancelled) setTopTags(data.tags ?? []);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [limit]);

  // Fetch suggestions on query change (debounced 200ms)
  const fetchSuggestions = useCallback((q: string) => {
    if (!q.trim()) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const url = `${API_BASE}/v1/tags/suggestions?q=${encodeURIComponent(q.trim())}&limit=${limit}`;
    fetch(url, { credentials: 'include' })
      .then(r => r.ok ? r.json() : { tags: [] })
      .then(data => {
        setSuggestions(data.tags ?? []);
        setLoading(false);
      })
      .catch(() => { setSuggestions([]); setLoading(false); });
  }, [limit]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(query), 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, fetchSuggestions]);

  return { suggestions, topTags, loading };
}
