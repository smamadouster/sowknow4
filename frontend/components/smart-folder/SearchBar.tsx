"use client";

import { useState, FormEvent } from "react";

interface SearchBarProps {
  onSubmit: (query: string) => void;
  loading?: boolean;
  placeholder?: string;
}

export default function SearchBar({ onSubmit, loading = false, placeholder = "Ask about any relationship, project, or topic…" }: SearchBarProps) {
  const [query, setQuery] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim() || loading) return;
    onSubmit(query.trim());
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-3xl mx-auto">
      <div className="relative flex items-center">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          disabled={loading}
          className="w-full px-6 py-4 pr-36 text-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-2xl shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 transition"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="absolute right-2 px-6 py-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition font-medium"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Generating…
            </span>
          ) : (
            "Generate"
          )}
        </button>
      </div>
    </form>
  );
}
