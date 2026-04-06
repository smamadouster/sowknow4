'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

interface MobileBottomSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  heightPercent?: number;
}

const DISMISS_THRESHOLD = 0.25;

export default function MobileBottomSheet({ open, onClose, title, children, heightPercent = 50 }: MobileBottomSheetProps) {
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
    const sheetHeight = (window.innerHeight * heightPercent) / 100;
    if (dragOffset > sheetHeight * DISMISS_THRESHOLD) {
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
  }, [dragOffset, heightPercent, onClose]);

  if (!open && !isClosing) return null;

  return (
    <>
      <div
        className={`fixed inset-0 z-50 bg-black/50 transition-opacity duration-200 ${
          isClosing ? 'opacity-0' : 'opacity-100'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title || 'Menu'}
        className={`fixed inset-x-0 bottom-0 z-50 bg-vault-950 rounded-t-2xl shadow-2xl flex flex-col ${
          isClosing ? 'animate-sheet-down' : 'animate-sheet-up'
        }`}
        style={{
          maxHeight: `${heightPercent}vh`,
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

        {title && (
          <div className="flex items-center justify-between px-4 pb-3 border-b border-white/[0.06]">
            <h2 className="text-sm font-semibold text-text-primary font-display">{title}</h2>
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
        )}

        <div className="flex-1 overflow-y-auto px-4 py-3 pb-safe">
          {children}
        </div>
      </div>
    </>
  );
}
