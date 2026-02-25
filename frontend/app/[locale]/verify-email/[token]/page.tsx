'use client';

import { useEffect, useState, useRef } from 'react';
import { useParams } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';

type VerifyState = 'loading' | 'success' | 'expired' | 'invalid' | 'network_error';

const REDIRECT_DELAY = 3; // seconds

export default function VerifyEmailPage() {
  const t = useTranslations('verify_email');
  const tc = useTranslations('common');
  const locale = useLocale();
  const params = useParams();
  const token = params.token as string;

  const [state, setState] = useState<VerifyState>('loading');
  const [countdown, setCountdown] = useState(REDIRECT_DELAY);
  const [resendEmail, setResendEmail] = useState('');
  const [resendLoading, setResendLoading] = useState(false);
  const [resendDone, setResendDone] = useState(false);
  const [resendError, setResendError] = useState('');
  const didVerify = useRef(false);

  useEffect(() => {
    if (didVerify.current) return;
    didVerify.current = true;

    const verify = async () => {
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api';
        const response = await fetch(`${apiUrl}/v1/auth/verify-email/${token}`, {
          method: 'POST',
        });

        if (response.ok) {
          setState('success');
        } else if (response.status === 400) {
          setState('expired');
        } else {
          setState('invalid');
        }
      } catch {
        setState('network_error');
      }
    };

    verify();
  }, [token]);

  // Countdown + redirect on success
  useEffect(() => {
    if (state !== 'success') return;

    if (countdown <= 0) {
      window.location.href = `/${locale}/login`;
      return;
    }

    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [state, countdown, locale]);

  const handleResend = async (e: React.FormEvent) => {
    e.preventDefault();
    setResendError('');
    setResendLoading(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api';
      const response = await fetch(`${apiUrl}/v1/auth/resend-verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: resendEmail }),
      });

      if (response.status === 429) {
        setResendError(t('resend_rate_limit'));
      } else if (response.ok) {
        setResendDone(true);
      } else {
        setResendError(t('resend_error'));
      }
    } catch {
      setResendError(t('resend_error'));
    } finally {
      setResendLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="bg-white p-8 rounded-xl shadow-lg w-full max-w-md text-center">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">SOWKNOW</h1>

        {/* LOADING */}
        {state === 'loading' && (
          <div className="mt-6">
            <div className="mx-auto w-12 h-12 flex items-center justify-center mb-4">
              <svg className="animate-spin h-10 w-10 text-yellow-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
            <p className="text-gray-600">{tc('loading')}</p>
          </div>
        )}

        {/* SUCCESS */}
        {state === 'success' && (
          <div className="mt-6">
            <div className="mx-auto w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900">{t('success_title')}</h2>
            <p className="text-gray-600 mt-3 text-sm">{t('success_desc')}</p>
            <p className="text-gray-500 text-sm mt-4">
              {t('redirect_countdown', { seconds: countdown })}
            </p>
            <a
              href={`/${locale}/login`}
              className="inline-block mt-6 w-full bg-yellow-400 text-gray-900 py-3 rounded-lg font-medium hover:bg-yellow-500 focus:ring-2 focus:ring-yellow-400 focus:ring-offset-2 transition-colors"
            >
              {t('go_to_login')}
            </a>
          </div>
        )}

        {/* EXPIRED TOKEN — show resend form */}
        {state === 'expired' && (
          <div className="mt-6">
            <div className="mx-auto w-16 h-16 bg-orange-100 rounded-full flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900">{t('expired_title')}</h2>
            <p className="text-gray-600 mt-3 text-sm">{t('expired_desc')}</p>

            {!resendDone ? (
              <form onSubmit={handleResend} className="mt-6 space-y-4 text-left">
                {resendError && (
                  <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
                    {resendError}
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('your_email')}
                  </label>
                  <input
                    type="email"
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    required
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-yellow-400 focus:border-transparent transition-colors"
                    placeholder="email@example.com"
                  />
                </div>
                <button
                  type="submit"
                  disabled={resendLoading}
                  className="w-full bg-yellow-400 text-gray-900 py-3 rounded-lg font-medium hover:bg-yellow-500 focus:ring-2 focus:ring-yellow-400 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                >
                  {resendLoading && (
                    <svg className="animate-spin h-4 w-4 text-gray-700" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  )}
                  {resendLoading ? tc('loading') : t('resend_button')}
                </button>
              </form>
            ) : (
              <div className="mt-6 bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded text-sm">
                {t('resend_success')}
              </div>
            )}

            <div className="mt-6">
              <a href={`/${locale}/login`} className="text-sm text-blue-600 hover:underline">
                {t('back_to_login')}
              </a>
            </div>
          </div>
        )}

        {/* INVALID TOKEN */}
        {state === 'invalid' && (
          <div className="mt-6">
            <div className="mx-auto w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900">{t('invalid_title')}</h2>
            <p className="text-gray-600 mt-3 text-sm">{t('invalid_desc')}</p>
            <a
              href={`/${locale}/login`}
              className="inline-block mt-6 w-full bg-yellow-400 text-gray-900 py-3 rounded-lg font-medium hover:bg-yellow-500 focus:ring-2 focus:ring-yellow-400 focus:ring-offset-2 transition-colors"
            >
              {t('back_to_login')}
            </a>
          </div>
        )}

        {/* NETWORK ERROR */}
        {state === 'network_error' && (
          <div className="mt-6">
            <div className="mx-auto w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900">{t('network_error_title')}</h2>
            <p className="text-gray-600 mt-3 text-sm">{t('network_error_desc')}</p>
            <button
              onClick={() => {
                didVerify.current = false;
                setState('loading');
                // re-trigger effect by resetting ref then re-running
                setTimeout(() => {
                  didVerify.current = false;
                  const verify = async () => {
                    try {
                      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api';
                      const response = await fetch(`${apiUrl}/v1/auth/verify-email/${token}`, {
                        method: 'POST',
                      });
                      if (response.ok) setState('success');
                      else if (response.status === 400) setState('expired');
                      else setState('invalid');
                    } catch {
                      setState('network_error');
                    }
                  };
                  verify();
                }, 0);
              }}
              className="inline-block mt-6 w-full bg-yellow-400 text-gray-900 py-3 rounded-lg font-medium hover:bg-yellow-500 focus:ring-2 focus:ring-yellow-400 focus:ring-offset-2 transition-colors"
            >
              {t('retry')}
            </button>
            <div className="mt-4">
              <a href={`/${locale}/login`} className="text-sm text-blue-600 hover:underline">
                {t('back_to_login')}
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
