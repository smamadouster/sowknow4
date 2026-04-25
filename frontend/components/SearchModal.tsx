'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { api } from '@/lib/api';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface SuggestionItem {
  id: string;
  title: string;
  type: 'document' | 'bookmark' | 'note' | 'tag';
  bucket?: string | null;
}

const TYPE_ICONS: Record<string, string> = {
  document: '📄',
  bookmark: '🔖',
  note: '📝',
  tag: '🏷️',
};

export default function SearchModal({ isOpen, onClose }: SearchModalProps) {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const router = useRouter();
  const locale = useLocale();
  const t = useTranslations('search_modal');

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSuggestions([]);
      setShowSuggestions(false);
      setActiveIndex(-1);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isOpen, onClose]);

  const fetchSuggestions = useCallback(async (value: string) => {
    if (!value.trim()) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    try {
      const res = await api.suggest(value.trim(), 5);
      if (res.data && res.data.suggestions) {
        setSuggestions(res.data.suggestions);
        setShowSuggestions(res.data.suggestions.length > 0);
        setActiveIndex(-1);
      } else {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    } catch {
      setSuggestions([]);
      setShowSuggestions(false);
    }
  }, []);

  const handleInputChange = useCallback((value: string) => {
    setQuery(value);
    setActiveIndex(-1);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (value.trim().length >= 1) {
      debounceRef.current = setTimeout(() => {
        fetchSuggestions(value);
      }, 150);
    } else {
      setSuggestions([]);
      setShowSuggestions(false);
    }
  }, [fetchSuggestions]);

  const navigateToSuggestion = useCallback((item: SuggestionItem) => {
    if (item.type === 'document') {
      router.push(`/${locale}/documents/${item.id}`);
    } else if (item.type === 'bookmark') {
      router.push(`/${locale}/bookmarks`);
    } else if (item.type === 'note') {
      router.push(`/${locale}/notes/${item.id}`);
    } else if (item.type === 'tag') {
      router.push(`/${locale}/documents?tag=${encodeURIComponent(item.title)}`);
    }
    onClose();
  }, [router, locale, onClose]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showSuggestions || suggestions.length === 0) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (query.trim()) {
          router.push(`/${locale}/search?q=${encodeURIComponent(query.trim())}`);
          onClose();
        }
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => (prev + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0 && activeIndex < suggestions.length) {
        navigateToSuggestion(suggestions[activeIndex]);
      } else if (query.trim()) {
        router.push(`/${locale}/search?q=${encodeURIComponent(query.trim())}`);
        onClose();
      }
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
      setActiveIndex(-1);
    }
  }, [showSuggestions, suggestions, activeIndex, query, router, locale, onClose, navigateToSuggestion]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    router.push(`/${locale}/search?q=${encodeURIComponent(query.trim())}`);
    onClose();
  }, [query, router, locale, onClose]);

  const quickLinks = [
    { label: t('quick_search'), href: `/${locale}/search`, icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    )},
    { label: t('quick_documents'), href: `/${locale}/documents`, icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    )},
    { label: t('quick_chat'), href: `/${locale}/chat`, icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
      </svg>
    )},
    { label: t('quick_collections'), href: `/${locale}/collections`, icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    )},
    { label: t('quick_bookmarks'), href: `/${locale}/bookmarks`, icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
      </svg>
    )},
  ];

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] px-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-vault-1000/80 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-xl animate-scale-in">
        <div className="bg-vault-900 border border-white/[0.08] rounded-2xl shadow-2xl shadow-black/50 overflow-hidden">
          {/* Search input */}
          <form onSubmit={handleSubmit}>
            <div className="flex items-center gap-3 px-5 py-4 border-b border-white/[0.06]">
              <svg className="w-5 h-5 text-text-muted shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => handleInputChange(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t('placeholder')}
                className="flex-1 bg-transparent text-text-primary text-base placeholder:text-text-muted/60 outline-none font-sans"
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
              />
              <kbd className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 bg-vault-800 border border-white/[0.08] rounded-md text-[10px] text-text-muted font-mono">
                ESC
              </kbd>
            </div>
          </form>

          {/* Suggestions dropdown */}
          {showSuggestions && suggestions.length > 0 && (
            <div className="px-3 py-2 border-b border-white/[0.06]">
              <p className="px-2 mb-1.5 text-[10px] font-semibold text-text-muted/60 uppercase tracking-widest">
                Suggestions
              </p>
              <div className="space-y-0.5">
                {suggestions.map((s, idx) => (
                  <button
                    key={`${s.type}-${s.id}`}
                    onClick={() => navigateToSuggestion(s)}
                    onMouseEnter={() => setActiveIndex(idx)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors duration-150 group text-left ${
                      idx === activeIndex
                        ? 'bg-white/[0.08] text-text-primary'
                        : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
                    }`}
                  >
                    <span className="text-base shrink-0">{TYPE_ICONS[s.type] || '•'}</span>
                    <span className="flex-1 truncate">{s.title}</span>
                    <span className="text-[10px] uppercase tracking-wider text-text-muted/50 shrink-0">
                      {s.type}
                    </span>
                    {s.bucket === 'confidential' && (
                      <span className="text-[10px] text-amber-400 shrink-0">🔒</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Quick navigation */}
          {!showSuggestions && (
            <div className="px-3 py-3">
              <p className="px-2 mb-2 text-[10px] font-semibold text-text-muted/60 uppercase tracking-widest">
                {t('navigate')}
              </p>
              <div className="space-y-0.5">
                {quickLinks.map((link) => (
                  <button
                    key={link.href}
                    onClick={() => { router.push(link.href); onClose(); }}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-text-secondary hover:text-text-primary hover:bg-white/[0.04] transition-colors duration-150 group"
                  >
                    <span className="text-text-muted group-hover:text-amber-400 transition-colors">
                      {link.icon}
                    </span>
                    <span>{link.label}</span>
                    <svg className="w-3.5 h-3.5 ml-auto text-text-muted/40 group-hover:text-text-muted transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Footer hint */}
          <div className="px-5 py-3 border-t border-white/[0.06] bg-vault-950/50 flex items-center justify-between">
            <div className="flex items-center gap-3 text-[10px] text-text-muted/50">
              <span className="flex items-center gap-1">
                <kbd className="px-1.5 py-0.5 bg-vault-800 border border-white/[0.06] rounded text-[9px] font-mono">
                  {t('enter')}
                </kbd>
                {t('to_search')}
              </span>
              <span className="flex items-center gap-1">
                <kbd className="px-1.5 py-0.5 bg-vault-800 border border-white/[0.06] rounded text-[9px] font-mono">ESC</kbd>
                {t('to_close')}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-amber-400/50">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              <span>AI-powered</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
