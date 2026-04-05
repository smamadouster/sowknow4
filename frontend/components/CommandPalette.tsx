'use client';

import { useEffect, useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import SearchModal from './SearchModal';

export default function CommandPalette() {
  const [isOpen, setIsOpen] = useState(false);
  const t = useTranslations('search_modal');

  const handleOpen = useCallback(() => setIsOpen(true), []);
  const handleClose = useCallback(() => setIsOpen(false), []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <>
      {/* Trigger button in header */}
      <button
        onClick={handleOpen}
        className="flex items-center gap-2 px-3 py-1.5 bg-vault-900/60 border border-white/[0.06] rounded-xl text-sm text-text-muted hover:text-text-secondary hover:border-white/[0.1] hover:bg-vault-900 transition-all duration-200 group"
      >
        <svg className="w-3.5 h-3.5 text-text-muted/60 group-hover:text-amber-400 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <span className="hidden sm:inline text-xs">{t('search_hint')}</span>
        <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-vault-800 border border-white/[0.08] rounded-md text-[10px] text-text-muted/60 font-mono ml-1">
          <span className="text-[9px]">⌘</span>K
        </kbd>
      </button>

      <SearchModal isOpen={isOpen} onClose={handleClose} />
    </>
  );
}
