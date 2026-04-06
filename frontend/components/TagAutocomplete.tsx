'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useTagSuggestions, TagSuggestion } from '@/hooks/useTagSuggestions';

interface TagItem {
  tag_name: string;
  tag_type?: string;
}

interface TagAutocompleteProps {
  tags: TagItem[];
  onChange: (tags: TagItem[]) => void;
  required?: boolean;
  placeholder?: string;
}

export default function TagAutocomplete({
  tags,
  onChange,
  required = false,
  placeholder = 'Add tag...',
}: TagAutocompleteProps) {
  const [input, setInput] = useState('');
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { suggestions, topTags, loading } = useTagSuggestions(input);

  const isAlreadyAdded = useCallback(
    (name: string) => tags.some(t => t.tag_name === name.toLowerCase().trim()),
    [tags]
  );

  const addTag = useCallback(
    (name: string) => {
      const trimmed = name.trim().toLowerCase();
      if (!trimmed || isAlreadyAdded(trimmed)) return;
      onChange([...tags, { tag_name: trimmed, tag_type: 'custom' }]);
      setInput('');
    },
    [tags, onChange, isAlreadyAdded]
  );

  const removeTag = useCallback(
    (tagName: string) => onChange(tags.filter(t => t.tag_name !== tagName)),
    [tags, onChange]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        addTag(input);
      }
      if (e.key === 'Backspace' && !input && tags.length > 0) {
        removeTag(tags[tags.length - 1].tag_name);
      }
      if (e.key === 'Escape') {
        setFocused(false);
        inputRef.current?.blur();
      }
    },
    [addTag, input, tags, removeTag]
  );

  // Close dropdown when clicking outside
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setFocused(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const showTopChips = focused && !input.trim() && topTags.length > 0;
  const showDropdown = focused && input.trim().length > 0;

  // Determine whether "Create" option should appear
  const hasExactMatch = suggestions.some(
    s => s.tag_name.toLowerCase() === input.trim().toLowerCase()
  );
  const showCreate = showDropdown && input.trim() && !hasExactMatch && !loading;

  return (
    <div ref={containerRef} className="relative space-y-2">
      {/* Selected tag pills */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map(tag => (
            <span
              key={tag.tag_name}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-sm rounded-full border bg-amber-500/10 text-amber-400 border-amber-500/20"
            >
              {tag.tag_name}
              <button
                type="button"
                onClick={() => removeTag(tag.tag_name)}
                aria-label={`Remove tag ${tag.tag_name}`}
                className="ml-0.5 text-amber-400/70 hover:text-amber-300 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center -my-2 -mr-1"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Top tag chips (shown when focused, no query) — ABOVE input via flex-col-reverse */}
      {showTopChips && (
        <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
          {topTags
            .filter(t => !isAlreadyAdded(t.tag_name))
            .map((t: TagSuggestion) => (
              <button
                key={t.tag_name}
                type="button"
                onMouseDown={e => { e.preventDefault(); addTag(t.tag_name); }}
                className="flex-shrink-0 px-3 py-2 text-sm rounded-full border border-white/10 bg-white/5 text-white/70 hover:bg-amber-500/20 hover:text-amber-300 hover:border-amber-500/30 transition-colors min-h-[44px] whitespace-nowrap"
              >
                {t.tag_name}
              </button>
            ))}
        </div>
      )}

      {/* Suggestion dropdown — rendered ABOVE the input on mobile */}
      {showDropdown && (suggestions.length > 0 || showCreate) && (
        <div className="absolute bottom-[calc(100%+4px)] left-0 right-0 z-50 rounded-xl border border-white/10 bg-[#1a1a2e]/95 backdrop-blur-sm shadow-2xl overflow-hidden">
          <ul className="max-h-52 overflow-y-auto py-1" role="listbox">
            {suggestions
              .filter(s => !isAlreadyAdded(s.tag_name))
              .map((s: TagSuggestion) => (
                <li key={s.tag_name} role="option" aria-selected={false}>
                  <button
                    type="button"
                    onMouseDown={e => { e.preventDefault(); addTag(s.tag_name); }}
                    className="w-full flex items-center justify-between px-4 text-sm text-white/80 hover:bg-amber-500/10 hover:text-amber-300 transition-colors min-h-[44px]"
                  >
                    <span>{s.tag_name}</span>
                    {s.count > 0 && (
                      <span className="text-xs text-white/30 ml-2">{s.count}</span>
                    )}
                  </button>
                </li>
              ))}
            {showCreate && (
              <li role="option" aria-selected={false}>
                <button
                  type="button"
                  onMouseDown={e => { e.preventDefault(); addTag(input); }}
                  className="w-full flex items-center gap-2 px-4 text-sm text-amber-400 hover:bg-amber-500/10 transition-colors min-h-[44px]"
                >
                  <span className="text-amber-500/60">+</span>
                  Create &ldquo;{input.trim()}&rdquo;
                </button>
              </li>
            )}
          </ul>
        </div>
      )}

      {/* Input row */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocused(true)}
            placeholder={placeholder}
            className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/30 min-h-[44px] text-sm"
          />
          {loading && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 text-xs">
              …
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => addTag(input)}
          disabled={!input.trim()}
          className="px-3 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors min-h-[44px] min-w-[44px] text-lg leading-none"
        >
          +
        </button>
      </div>

      {required && tags.length === 0 && (
        <p className="text-sm text-red-400">At least one tag is required</p>
      )}
    </div>
  );
}
