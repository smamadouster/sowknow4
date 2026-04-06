'use client';

import { useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useIsMobile } from '@/hooks/useIsMobile';
import TagAutocomplete from '@/components/TagAutocomplete';

interface TagItem {
  tag_name: string;
  tag_type?: string;
}

interface TagSelectorProps {
  tags: TagItem[];
  onChange: (tags: TagItem[]) => void;
  required?: boolean;
  placeholder?: string;
}

export default function TagSelector({ tags, onChange, required = false, placeholder }: TagSelectorProps) {
  const tCommon = useTranslations('common');
  const isMobile = useIsMobile();
  const [input, setInput] = useState('');

  const addTag = useCallback(() => {
    const trimmed = input.trim().toLowerCase();
    if (!trimmed) return;
    if (tags.some(t => t.tag_name === trimmed)) {
      setInput('');
      return;
    }
    onChange([...tags, { tag_name: trimmed, tag_type: 'custom' }]);
    setInput('');
  }, [input, tags, onChange]);

  const removeTag = useCallback((tagName: string) => {
    onChange(tags.filter(t => t.tag_name !== tagName));
  }, [tags, onChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag();
    }
    if (e.key === 'Backspace' && !input && tags.length > 0) {
      removeTag(tags[tags.length - 1].tag_name);
    }
  }, [addTag, input, tags, removeTag]);

  if (isMobile) {
    return (
      <TagAutocomplete
        tags={tags}
        onChange={onChange}
        required={required}
        placeholder={placeholder}
      />
    );
  }

  // Desktop: original inline tag input, vault-themed
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 min-h-[32px]">
        {tags.map(tag => (
          <span
            key={tag.tag_name}
            className="inline-flex items-center gap-1 px-2 py-1 text-sm rounded-full border bg-amber-500/10 text-amber-400 border-amber-500/20"
          >
            {tag.tag_name}
            <button
              type="button"
              onClick={() => removeTag(tag.tag_name)}
              className="ml-1 text-amber-400/70 hover:text-amber-300 transition-colors"
            >
              &times;
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || 'Add tag...'}
          className="flex-1 px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/30 text-sm"
        />
        <button
          type="button"
          onClick={addTag}
          disabled={!input.trim()}
          className="px-3 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
