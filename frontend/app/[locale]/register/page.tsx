'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';

export default function RegisterPage() {
  const t = useTranslations('auth');
  const router = useRouter();
  const locale = useLocale();
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    confirmPassword: '',
    full_name: '',
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (formData.password !== formData.confirmPassword) {
      setError(t('passwords_do_not_match'));
      return;
    }

    setLoading(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '/api';
      const response = await fetch(`${apiUrl}/v1/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: formData.email, password: formData.password, full_name: formData.full_name }),
        credentials: 'include',
      });

      if (response.ok) {
        router.push(`/${locale}/login?registered=true`);
      } else {
        const data = await response.json();
        setError(data.detail || t('register_error'));
      }
    } catch (err) {
      setError(t('register_error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-vault-1000 relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-emerald-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 left-1/4 w-80 h-80 bg-blue-500/5 rounded-full blur-3xl" />
        <div className="absolute inset-0 opacity-[0.015]" style={{
          backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.5) 1px, transparent 0)',
          backgroundSize: '40px 40px',
        }} />
      </div>

      <div className="relative w-full max-w-md mx-4">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-emerald-400 to-emerald-600 shadow-lg shadow-emerald-500/20 mb-4">
            <svg className="w-9 h-9 text-vault-1000" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
              <circle cx="8.5" cy="7" r="4" />
              <path d="M20 8v6" />
              <path d="M23 11h-6" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-text-primary font-display">SOWKNOW</h1>
          <p className="text-text-muted mt-1 text-sm">{t('register_title')}</p>
        </div>

        <div className="bg-vault-900/60 backdrop-blur-xl border border-white/[0.08] rounded-2xl p-6 sm:p-8 shadow-card">
          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div role="alert" id="register-error" className="bg-red-500/10 border border-red-500/20 text-red-300 px-4 py-3 rounded-xl text-sm">
                {error}
              </div>
            )}

            <div>
              <label htmlFor="reg-full-name" className="block text-xs font-medium text-text-muted mb-2 uppercase tracking-wider">
                {t('full_name')}
              </label>
              <input
                id="reg-full-name"
                type="text"
                value={formData.full_name}
                onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                required
                aria-describedby={error ? 'register-error' : undefined}
                className="w-full px-4 py-3 bg-vault-800/50 border border-white/[0.08] rounded-xl text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-all"
                placeholder="John Doe"
                autoComplete="name"
              />
            </div>

            <div>
              <label htmlFor="reg-email" className="block text-xs font-medium text-text-muted mb-2 uppercase tracking-wider">
                {t('email')}
              </label>
              <input
                id="reg-email"
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                required
                aria-describedby={error ? 'register-error' : undefined}
                className="w-full px-4 py-3 bg-vault-800/50 border border-white/[0.08] rounded-xl text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-all"
                placeholder="email@example.com"
                autoComplete="email"
              />
            </div>

            <div>
              <label htmlFor="reg-password" className="block text-xs font-medium text-text-muted mb-2 uppercase tracking-wider">
                {t('password')}
              </label>
              <input
                id="reg-password"
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                required
                aria-describedby={error ? 'register-error' : undefined}
                className="w-full px-4 py-3 bg-vault-800/50 border border-white/[0.08] rounded-xl text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-all"
                placeholder="••••••••"
                autoComplete="new-password"
              />
            </div>

            <div>
              <label htmlFor="reg-confirm-password" className="block text-xs font-medium text-text-muted mb-2 uppercase tracking-wider">
                {t('confirm_password')}
              </label>
              <input
                id="reg-confirm-password"
                type="password"
                value={formData.confirmPassword}
                onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                required
                aria-describedby={error ? 'register-error' : undefined}
                className="w-full px-4 py-3 bg-vault-800/50 border border-white/[0.08] rounded-xl text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-all"
                placeholder="••••••••"
                autoComplete="new-password"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              aria-busy={loading}
              className="w-full bg-gradient-to-r from-emerald-500 to-emerald-600 text-vault-1000 py-3 rounded-xl font-semibold hover:from-emerald-400 hover:to-emerald-500 focus:ring-2 focus:ring-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 font-display"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <div className="w-4 h-4 border-2 border-vault-1000/30 border-t-vault-1000 rounded-full animate-spin" />
                  {t('register_button')}
                </span>
              ) : t('register_button')}
            </button>
          </form>
        </div>

        <div className="mt-6 text-center">
          <p className="text-sm text-text-muted">
            {t('has_account')}{' '}
            <a href={`/${locale}/login`} className="text-amber-400 hover:text-amber-300 font-medium transition-colors">
              {t('login_button')}
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
