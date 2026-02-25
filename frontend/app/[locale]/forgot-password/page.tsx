'use client';

import { useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_ATTEMPTS = 3;

export default function ForgotPasswordPage() {
  const t = useTranslations('auth');
  const tc = useTranslations('common');
  const locale = useLocale();
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const [attempts, setAttempts] = useState(0);
  const [rateLimited, setRateLimited] = useState(false);

  const validateEmail = (value: string): boolean => {
    if (!EMAIL_REGEX.test(value)) {
      setEmailError(t('invalid_email'));
      return false;
    }
    setEmailError('');
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!validateEmail(email)) return;

    // Client-side rate limiting UI feedback
    const newAttempts = attempts + 1;
    setAttempts(newAttempts);
    if (newAttempts > MAX_ATTEMPTS) {
      setRateLimited(true);
      setError(t('forgot_password_rate_limit'));
      return;
    }

    setLoading(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api';
      const response = await fetch(`${apiUrl}/v1/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      if (response.status === 429) {
        setRateLimited(true);
        setError(t('forgot_password_rate_limit'));
        return;
      }

      if (response.ok) {
        setSuccess(true);
      } else {
        setError(t('forgot_password_error'));
      }
    } catch {
      setError(t('forgot_password_error'));
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
        <div className="bg-white p-8 rounded-xl shadow-lg w-full max-w-md text-center">
          <div className="mb-6">
            <div className="mx-auto w-16 h-16 bg-yellow-100 rounded-full flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-yellow-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900">{t('forgot_password_success_title')}</h2>
            <p className="text-gray-600 mt-3 text-sm leading-relaxed">
              {t('forgot_password_success_desc')}
            </p>
          </div>
          <a
            href={`/${locale}/login`}
            className="inline-block w-full bg-yellow-400 text-gray-900 py-3 rounded-lg font-medium hover:bg-yellow-500 focus:ring-2 focus:ring-yellow-400 focus:ring-offset-2 transition-colors text-center"
          >
            {t('back_to_login')}
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="bg-white p-8 rounded-xl shadow-lg w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900">SOWKNOW</h1>
          <p className="text-gray-600 mt-2">{t('forgot_password_title')}</p>
          <p className="text-gray-500 text-sm mt-2">{t('forgot_password_desc')}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('email')}
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                if (emailError) validateEmail(e.target.value);
              }}
              onBlur={(e) => validateEmail(e.target.value)}
              disabled={rateLimited}
              required
              className={`w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-yellow-400 focus:border-transparent transition-colors ${
                emailError ? 'border-red-400 bg-red-50' : 'border-gray-300'
              } ${rateLimited ? 'opacity-50 cursor-not-allowed' : ''}`}
              placeholder="email@example.com"
            />
            {emailError && (
              <p className="text-red-600 text-xs mt-1">{emailError}</p>
            )}
          </div>

          {attempts > 0 && attempts <= MAX_ATTEMPTS && !rateLimited && (
            <p className="text-xs text-gray-500 text-center">
              {t('forgot_password_attempts_remaining', { count: MAX_ATTEMPTS - attempts })}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || rateLimited}
            className="w-full bg-yellow-400 text-gray-900 py-3 rounded-lg font-medium hover:bg-yellow-500 focus:ring-2 focus:ring-yellow-400 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {loading && (
              <svg className="animate-spin h-4 w-4 text-gray-700" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {loading ? tc('loading') : t('forgot_password_button')}
          </button>
        </form>

        <div className="mt-6 text-center">
          <a href={`/${locale}/login`} className="text-sm text-blue-600 hover:underline">
            {t('back_to_login')}
          </a>
        </div>
      </div>
    </div>
  );
}
