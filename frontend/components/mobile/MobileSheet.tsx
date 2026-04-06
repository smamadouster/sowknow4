'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

interface MobileSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  headerActions?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}

const DISMISS_THRESHOLD = 0.3;

export default function MobileSheet({ open, onClose, title, headerActions, footer, children }: MobileSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const dragStartY = useRef<number | null>(null);
  const [dragOffset, setDragOffset] = useState(0);
  const [isClosing, setIsClosing] = useState(false);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0];
    const rect = sheetRef.current?.getBoundingClientRect();
    if (rect && touch.clientY - rect.top < 60) {
      dragStartY.current = touch.clientY;
    }
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (dragStartY.current === null) return;
    const delta = e.touches[0].clientY - dragStartY.current;
    if (delta > 0) {
      setDragOffset(delta);
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (dragStartY.current === null) return;
    const screenHeight = window.innerHeight;
    if (dragOffset > screenHeight * DISMISS_THRESHOLD) {
      setIsClosing(true);
      setTimeout(() => {
        onClose();
        setIsClosing(false);
        setDragOffset(0);
      }, 200);
    } else {
      setDragOffset(0);
    }
    dragStartY.current = null;
  }, [dragOffset, onClose]);

  if (!open && !isClosing) return null;

  return (
    <>
      <div
        className={`fixed inset-0 z-50 bg-black/60 backdrop-blur-sm transition-opacity duration-200 ${
          isClosing ? 'opacity-0' : 'opacity-100'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title || 'Sheet'}
        className={`fixed inset-x-0 bottom-0 z-50 bg-vault-950 rounded-t-2xl shadow-2xl flex flex-col ${
          isClosing ? 'animate-sheet-down' : 'animate-sheet-up'
        }`}
        style={{
          top: 'env(safe-area-inset-top, 0px)',
          transform: dragOffset > 0 ? `translateY(${dragOffset}px)` : undefined,
          transition: dragOffset > 0 ? 'none' : undefined,
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full bg-white/20" />
        </div>

        <div className="flex items-center justify-between px-4 pb-3 border-b border-white/[0.06]">
          <h2 className="text-base font-semibold text-text-primary font-display">{title}</h2>
          <div className="flex items-center gap-2">
            {headerActions}
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-white/[0.06] flex items-center justify-center text-text-muted hover:text-text-primary transition-colors"
              aria-label="Close"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {children}
        </div>

        {footer && (
          <div className="border-t border-white/[0.06] px-4 py-3 pb-safe bg-vault-950">
            {footer}
          </div>
        )}
      </div>
    </>
  );
}
