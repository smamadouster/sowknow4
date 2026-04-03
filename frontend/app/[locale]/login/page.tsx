'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';
import { useAuthStore } from '@/lib/store';

export default function LoginPage() {
  const t = useTranslations('auth');
  const router = useRouter();
  const locale = useLocale();
  const { setUser } = useAuthStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showTimeout, setShowTimeout] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('reason') === 'timeout') {
      setShowTimeout(true);
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api';
      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);
      
      const response = await fetch(`${apiUrl}/v1/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
        credentials: 'include',
      });

      if (response.ok) {
        const meResponse = await fetch(`${apiUrl}/v1/auth/me`, {
          credentials: 'include',
        });
        if (meResponse.ok) {
          const userData = await meResponse.json();
          setUser(userData);
        }
        router.push(`/${locale}`);
      } else {
        const data = await response.json();
        setError(data.detail || t('login_error'));
      }
    } catch (err) {
      setError(t('login_error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="bg-white p-8 rounded-xl shadow-lg w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900">SOWKNOW</h1>
          <p className="text-gray-600 mt-2">{t('login_title')}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {showTimeout && (
            <div role="status" className="bg-amber-50 border border-amber-200 text-amber-700 px-4 py-3 rounded">
              {t('session_expired')}
            </div>
          )}
          {error && (
            <div role="alert" id="login-error" className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-2">
              {t('email')}
            </label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              aria-describedby={error ? 'login-error' : undefined}
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="email@example.com"
              autoComplete="email"
            />
          </div>

          <div>
            <label htmlFor="login-password" className="block text-sm font-medium text-gray-700 mb-2">
              {t('password')}
            </label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              aria-describedby={error ? 'login-error' : undefined}
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="••••••••"
              autoComplete="current-password"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            aria-busy={loading}
            className="w-full bg-blue-600 text-white py-3 rounded-lg font-medium hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? t('login_button') + '...' : t('login_button')}
          </button>

          <div className="text-center">
            <a href={`/${locale}/forgot-password`} className="text-sm text-blue-600 hover:underline">
              {t('forgot_password')}
            </a>
          </div>
        </form>

        <div className="mt-6 text-center">
          <p className="text-sm text-gray-600">
            {t('no_account')}{' '}
            <a href={`/${locale}/register`} className="text-blue-600 hover:underline">
              {t('register_button')}
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
