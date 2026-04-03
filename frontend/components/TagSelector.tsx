'use client';

import { useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';

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

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 min-h-[32px]">
        {tags.map(tag => (
          <span
            key={tag.tag_name}
            className="inline-flex items-center gap-1 px-2 py-1 text-sm rounded-full bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200"
          >
            {tag.tag_name}
            <button
              type="button"
              onClick={() => removeTag(tag.tag_name)}
              className="ml-1 text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-200"
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
          className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500 focus:border-transparent"
        />
        <button
          type="button"
          onClick={addTag}
          disabled={!input.trim()}
          className="px-3 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          +
        </button>
      </div>
      {required && tags.length === 0 && (
        <p className="text-sm text-red-500">At least one tag is required</p>
      )}
    </div>
  );
}
