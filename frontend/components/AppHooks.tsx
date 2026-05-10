'use client';

import { useTaskAlarms } from '@/hooks/useTaskAlarms';
import { usePushNotifications } from '@/hooks/usePushNotifications';
import { useEffect } from 'react';

export default function AppHooks() {
  useTaskAlarms();
  const { isSupported, isSubscribed, subscribe } = usePushNotifications();

  // Auto-subscribe to push if supported and not yet subscribed
  useEffect(() => {
    if (isSupported && !isSubscribed) {
      // Delay to avoid interfering with initial page load
      const timer = setTimeout(() => {
        subscribe();
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [isSupported, isSubscribed, subscribe]);

  return null;
}
