'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useLocale } from 'next-intl';
import { useAuthStore } from '@/lib/store';

const TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes

/**
 * Auto-logout after 15 minutes of inactivity.
 * Resets the timer on user interaction (mouse, keyboard, touch, scroll).
 * Only active when the user is authenticated.
 */
export function useSessionTimeout() {
  const { isAuthenticated, logout } = useAuthStore();
  const router = useRouter();
  const locale = useLocale();
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const handleTimeout = useCallback(async () => {
    await logout();
    router.push(`/${locale}/login?reason=timeout`);
  }, [logout, router, locale]);

  const resetTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(handleTimeout, TIMEOUT_MS);
  }, [handleTimeout]);

  useEffect(() => {
    if (!isAuthenticated) return;

    const events = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'] as const;
    events.forEach((e) => document.addEventListener(e, resetTimer));
    resetTimer();

    return () => {
      events.forEach((e) => document.removeEventListener(e, resetTimer));
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [isAuthenticated, resetTimer]);
}
