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
    <div className="min-h-screen flex items-center justify-center bg-vault-1000 relative overflow-hidden">
      {/* Background effects */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-amber-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-blue-500/5 rounded-full blur-3xl" />
        <div className="absolute inset-0 opacity-[0.015]" style={{
          backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.5) 1px, transparent 0)',
          backgroundSize: '40px 40px',
        }} />
      </div>

      <div className="relative w-full max-w-md mx-4">
        {/* Logo & branding */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-amber-400 to-amber-600 shadow-lg shadow-amber-500/20 mb-4">
            <svg className="w-9 h-9 text-vault-1000" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-text-primary font-display">SOWKNOW</h1>
          <p className="text-text-muted mt-1 text-sm">{t('login_title')}</p>
        </div>

        {/* Login form card */}
        <div className="bg-vault-900/60 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-6 sm:p-8 shadow-card">
          <form onSubmit={handleSubmit} className="space-y-5">
            {showTimeout && (
              <div role="status" className="bg-amber-500/10 border border-amber-500/20 text-amber-300 px-4 py-3 rounded-xl text-sm">
                {t('session_expired')}
              </div>
            )}
            {error && (
              <div role="alert" id="login-error" className="bg-red-500/10 border border-red-500/20 text-red-300 px-4 py-3 rounded-xl text-sm">
                {error}
              </div>
            )}

            <div>
              <label htmlFor="login-email" className="block text-xs font-medium text-text-muted mb-2 uppercase tracking-wider">
                {t('email')}
              </label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                aria-describedby={error ? 'login-error' : undefined}
                className="w-full px-4 py-3 bg-vault-800/50 border border-white/[0.08] rounded-xl text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all"
                placeholder="email@example.com"
                autoComplete="email"
              />
            </div>

            <div>
              <label htmlFor="login-password" className="block text-xs font-medium text-text-muted mb-2 uppercase tracking-wider">
                {t('password')}
              </label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                aria-describedby={error ? 'login-error' : undefined}
                className="w-full px-4 py-3 bg-vault-800/50 border border-white/[0.08] rounded-xl text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all"
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              aria-busy={loading}
              className="w-full bg-gradient-to-r from-amber-500 to-amber-600 text-vault-1000 py-3 rounded-xl font-semibold hover:from-amber-400 hover:to-amber-500 focus:ring-2 focus:ring-amber-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-amber-500/20 hover:shadow-amber-500/30 font-display"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <div className="w-4 h-4 border-2 border-vault-1000/30 border-t-vault-1000 rounded-full animate-spin" />
                  {t('login_button')}
                </span>
              ) : t('login_button')}
            </button>

            <div className="text-center">
              <a href={`/${locale}/forgot-password`} className="text-sm text-amber-400/80 hover:text-amber-400 transition-colors">
                {t('forgot_password')}
              </a>
            </div>
          </form>
        </div>

        {/* Register link */}
        <div className="mt-6 text-center">
          <p className="text-sm text-text-muted">
            {t('no_account')}{' '}
            <a href={`/${locale}/register`} className="text-amber-400 hover:text-amber-300 font-medium transition-colors">
              {t('register_button')}
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
