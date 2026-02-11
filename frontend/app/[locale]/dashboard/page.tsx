'use client';

import { useTranslations } from 'next-intl';
import { useEffect } from 'react';

export default function DashboardPage() {
  const t = useTranslations('nav');

  useEffect(() => {
    // Redirect to collections page as main dashboard
    window.location.href = '/collections';
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
        <p className="text-gray-600">Loading dashboard...</p>
      </div>
    </div>
  );
}
