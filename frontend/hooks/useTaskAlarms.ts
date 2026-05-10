'use client';

import { useEffect, useRef } from 'react';

interface TaskItem {
  id: string;
  title: string;
  notes: string | null;
  alarm_at: string | null;
  alarm_triggered: boolean;
}

const CHECK_INTERVAL_MS = 30_000; // Check every 30 seconds

export function useTaskAlarms() {
  const notifiedTasks = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (typeof window === 'undefined') return;

    // Request notification permission on first mount
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }

    const checkAlarms = async () => {
      if ('Notification' in window && Notification.permission !== 'granted') return;

      try {
        const { api } = await import('@/lib/api');
        const response = await api.getTasks(1, 100);
        if (!response.data || response.error) return;

        const data = response.data as { tasks: TaskItem[] };
        const now = new Date();

        for (const task of data.tasks) {
          if (!task.alarm_at || task.alarm_triggered) continue;
          if (notifiedTasks.current.has(task.id)) continue;

          const alarmTime = new Date(task.alarm_at);
          if (alarmTime <= now) {
            notifiedTasks.current.add(task.id);
            new Notification('SOWKNOW Task Alarm', {
              body: task.title + (task.notes ? ` — ${task.notes}` : ''),
              icon: '/icon-192x192.png',
              badge: '/icon-72x72.png',
              tag: `task-${task.id}`,
              requireInteraction: true,
            });
          }
        }
      } catch (error) {
        console.error('Task alarm check failed:', error);
      }
    };

    checkAlarms();
    const interval = setInterval(checkAlarms, CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);
}
