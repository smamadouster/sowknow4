'use client';

import { useRef, useState, useCallback } from 'react';

interface SwipeableRowProps {
  children: React.ReactNode;
  onSwipeAction: () => void;
  actionLabel: string;
  actionColor?: string;
}

const SWIPE_THRESHOLD = 80;

export default function SwipeableRow({ children, onSwipeAction, actionLabel, actionColor = 'bg-red-500' }: SwipeableRowProps) {
  const startX = useRef<number | null>(null);
  const [offsetX, setOffsetX] = useState(0);
  const [showAction, setShowAction] = useState(false);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    startX.current = e.touches[0].clientX;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (startX.current === null) return;
    const diff = startX.current - e.touches[0].clientX;
    if (diff > 0) {
      setOffsetX(Math.min(diff, 120));
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (offsetX > SWIPE_THRESHOLD) {
      setShowAction(true);
      setOffsetX(100);
    } else {
      setOffsetX(0);
      setShowAction(false);
    }
    startX.current = null;
  }, [offsetX]);

  const handleActionClick = () => {
    onSwipeAction();
    setOffsetX(0);
    setShowAction(false);
  };

  const handleContentClick = () => {
    if (showAction) {
      setOffsetX(0);
      setShowAction(false);
    }
  };

  return (
    <div className="relative overflow-hidden rounded-lg md:overflow-visible">
      <div className={`absolute inset-y-0 right-0 flex items-center justify-center ${actionColor} text-white font-medium text-sm px-4`} style={{ width: '100px' }}>
        <button onClick={handleActionClick} className="w-full h-full flex items-center justify-center min-h-[44px]">
          {actionLabel}
        </button>
      </div>

      <div
        className="relative bg-vault-950 transition-transform"
        style={{
          transform: `translateX(-${offsetX}px)`,
          transition: startX.current !== null ? 'none' : 'transform 0.2s ease-out',
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onClick={handleContentClick}
      >
        {children}
      </div>
    </div>
  );
}
