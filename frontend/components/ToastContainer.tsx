'use client';

import { useEffect } from 'react';
import { useToastStore, type ToastType } from '@/lib/toast';

const typeStyles: Record<ToastType, string> = {
  success:
    'bg-emerald-500/15 border-emerald-500/25 text-emerald-400',
  error:
    'bg-red-500/15 border-red-500/25 text-red-400',
  info:
    'bg-amber-500/15 border-amber-500/25 text-amber-400',
};

function ToastItem({ id, message, type }: { id: string; message: string; type: ToastType }) {
  const hideToast = useToastStore((state) => state.hideToast);

  useEffect(() => {
    const timer = setTimeout(() => hideToast(id), 4000);
    return () => clearTimeout(timer);
  }, [id, hideToast]);

  return (
    <div
      role="status"
      className={`pointer-events-auto flex items-center gap-3 rounded-xl border px-4 py-3 shadow-lg backdrop-blur-md ${typeStyles[type]}`}
    >
      <span className="text-sm font-medium">{message}</span>
      <button
        onClick={() => hideToast(id)}
        className="ml-auto rounded p-1 hover:bg-white/10 transition-colors"
        aria-label="Close notification"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

export default function ToastContainer() {
  const toasts = useToastStore((state) => state.toasts);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm w-full px-4 sm:px-0">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} {...toast} />
      ))}
    </div>
  );
}
