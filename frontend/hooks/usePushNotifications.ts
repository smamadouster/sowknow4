'use client';

import { useEffect, useRef, useState } from 'react';

interface PushSubscriptionKeys {
  p256dh: string;
  auth: string;
}

interface PushSubscriptionData {
  endpoint: string;
  keys: PushSubscriptionKeys;
}

export function usePushNotifications() {
  const [isSupported, setIsSupported] = useState(false);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [vapidPublicKey, setVapidPublicKey] = useState('');
  const swRegistration = useRef<ServiceWorkerRegistration | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator) || !('PushManager' in window)) {
      return;
    }
    setIsSupported(true);

    // Fetch VAPID public key
    fetch('/api/v1/push/vapid-public-key')
      .then(r => r.json())
      .then(data => setVapidPublicKey(data.public_key || ''))
      .catch(() => {});

    navigator.serviceWorker.ready.then(reg => {
      swRegistration.current = reg;
      reg.pushManager.getSubscription().then(sub => {
        setIsSubscribed(!!sub);
      });
    });
  }, []);

  const urlBase64ToUint8Array = (base64String: string): Uint8Array => {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    return Uint8Array.from(rawData.split('').map(char => char.charCodeAt(0)));
  };

  const subscribe = async (): Promise<boolean> => {
    if (!swRegistration.current || !vapidPublicKey) return false;
    try {
      const subscription = await swRegistration.current.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidPublicKey) as unknown as ArrayBuffer,
      });
      const data = subscription.toJSON();
      const { api } = await import('@/lib/api');
      await api.subscribePush({
        endpoint: data.endpoint!,
        p256dh: data.keys!.p256dh,
        auth: data.keys!.auth,
      });
      setIsSubscribed(true);
      return true;
    } catch (error) {
      console.error('Push subscription failed:', error);
      return false;
    }
  };

  const unsubscribe = async (): Promise<boolean> => {
    if (!swRegistration.current) return false;
    try {
      const subscription = await swRegistration.current.pushManager.getSubscription();
      if (subscription) {
        const data = subscription.toJSON();
        const { api } = await import('@/lib/api');
        await api.unsubscribePush({
          endpoint: data.endpoint!,
          p256dh: data.keys!.p256dh,
          auth: data.keys!.auth,
        });
        await subscription.unsubscribe();
      }
      setIsSubscribed(false);
      return true;
    } catch (error) {
      console.error('Push unsubscription failed:', error);
      return false;
    }
  };

  return { isSupported, isSubscribed, subscribe, unsubscribe };
}
