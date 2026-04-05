'use client';

import { useTranslations } from 'next-intl';

export default function PrivacyBadge() {
  const t = useTranslations('privacy_badge');

  return (
    <div className="privacy-badge" title={t('local_processing')}>
      <span className="dot" />
      <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
      </svg>
      <span className="hidden sm:inline">{t('local_processing')}</span>
    </div>
  );
}
