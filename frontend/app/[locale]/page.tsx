'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Link as IntlLink } from '@/i18n/routing';
import { useAuthStore } from '@/lib/store';

interface ServiceCard {
  href: string;
  titleKey: string;
  descKey: string;
  icon: React.ReactNode;
  color: string;
  glowColor: string;
}

export default function Home() {
  const t = useTranslations('home');
  const tNav = useTranslations('nav');
  const [userRole, setUserRole] = useState<string>('user');
  const [userName, setUserName] = useState<string>('');
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (user) {
      setUserRole(user.role || 'user');
      setUserName(user.full_name || '');
    }
  }, [user]);

  const isAdmin = userRole === 'admin';
  const isSuperuser = userRole === 'superuser';
  const hasExtendedAccess = isAdmin || isSuperuser;

  const mainServices: ServiceCard[] = [
    {
      href: '/search',
      titleKey: 'search',
      descKey: 'search_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      ),
      color: 'from-blue-500/20 to-blue-600/5',
      glowColor: 'group-hover:shadow-blue-500/20',
    },
    {
      href: '/documents',
      titleKey: 'documents',
      descKey: 'documents_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
      color: 'from-emerald-500/20 to-emerald-600/5',
      glowColor: 'group-hover:shadow-emerald-500/20',
    },
    {
      href: '/chat',
      titleKey: 'chat',
      descKey: 'chat_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
        </svg>
      ),
      color: 'from-violet-500/20 to-violet-600/5',
      glowColor: 'group-hover:shadow-violet-500/20',
    },
    {
      href: '/collections',
      titleKey: 'collections',
      descKey: 'collections_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
      color: 'from-sky-500/20 to-sky-600/5',
      glowColor: 'group-hover:shadow-sky-500/20',
    },
    {
      href: '/smart-folders',
      titleKey: 'smart_folders',
      descKey: 'smart_folders_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
      ),
      color: 'from-teal-500/20 to-teal-600/5',
      glowColor: 'group-hover:shadow-teal-500/20',
    },
    {
      href: '/knowledge-graph',
      titleKey: 'knowledge_graph',
      descKey: 'knowledge_graph_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
      ),
      color: 'from-purple-500/20 to-purple-600/5',
      glowColor: 'group-hover:shadow-purple-500/20',
    },
    {
      href: '/bookmarks',
      titleKey: 'bookmarks',
      descKey: 'bookmarks_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
        </svg>
      ),
      color: 'from-rose-500/20 to-rose-600/5',
      glowColor: 'group-hover:shadow-rose-500/20',
    },
    {
      href: '/notes',
      titleKey: 'notes',
      descKey: 'notes_desc',
      icon: (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
        </svg>
      ),
      color: 'from-amber-500/20 to-amber-600/5',
      glowColor: 'group-hover:shadow-amber-500/20',
    },
  ];

  return (
    <div className="bg-vault-1000 relative overflow-hidden" style={{ minHeight: 'calc(100dvh - 8rem)' }}>
      {/* Background decorative elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-amber-500/5 rounded-full blur-3xl" />
        <div className="absolute top-1/2 -left-40 w-80 h-80 bg-blue-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-0 right-1/4 w-64 h-64 bg-violet-500/5 rounded-full blur-3xl" />
        {/* Dashed grid pattern overlay */}
        <div className="absolute inset-0 bg-grid-dashed" style={{
          maskImage: 'radial-gradient(ellipse at center, white 30%, transparent 70%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, white 30%, transparent 70%)',
        }} />
      </div>

      <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        {/* Welcome Hero */}
        <div className="text-center mb-12 sm:mb-16">
          {userName && (
            <p className="text-sm text-amber-400/80 mb-3 font-medium tracking-wide uppercase text-xs">
              {t('hello', { name: userName })}
            </p>
          )}
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-text-primary mb-4 leading-tight font-display tracking-heading">
            {t('welcome_title')}
          </h1>
          <div className="max-w-xl mx-auto bg-vault-900/50 backdrop-blur-sm rounded-2xl border border-white/[0.06] px-6 py-5 shadow-card">
            <p className="text-text-secondary text-base leading-relaxed">
              {t('welcome_message')}
            </p>
            <p className="text-amber-400/80 font-medium text-sm mt-3 tracking-wide">
              {t('welcome_discovery')}
            </p>
          </div>
        </div>

        {/* Main Services Grid */}
        <div className="mb-12">
          <div className="flex items-center gap-3 mb-6">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
            <h2 className="text-xs font-semibold text-text-muted uppercase tracking-widest font-display">
              {t('services_title')}
            </h2>
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 sm:gap-4">
            {mainServices.map((service, index) => (
              <IntlLink
                key={service.href}
                href={service.href}
                className="group"
              >
                <div
                  className={`relative bg-gradient-to-br ${service.color} backdrop-blur-sm rounded-2xl border border-white/[0.06] p-5 sm:p-6 h-full flex flex-col items-center text-center transition-all duration-350 hover:border-white/[0.14] hover:shadow-xl ${service.glowColor} hover:-translate-y-1.5 group-hover:bg-gradient-to-br`}
                  style={{ animationDelay: `${index * 50}ms` }}
                >
                  {/* Subtle inner glow on hover */}
                  <div className="absolute inset-0 rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" style={{ boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.06)' }} />
                  {/* Icon container */}
                  <div className="w-12 h-12 rounded-xl bg-vault-800/60 backdrop-blur-sm border border-white/[0.06] flex items-center justify-center mb-3 group-hover:scale-110 group-hover:border-white/[0.1] transition-all duration-300">
                    <span className="text-text-secondary group-hover:text-amber-400 transition-colors duration-300">
                      {service.icon}
                    </span>
                  </div>
                  <h3 className="font-semibold text-text-primary mb-1 text-sm sm:text-base font-display tracking-tight">{tNav(service.titleKey)}</h3>
                  <p className="text-text-muted text-xs leading-relaxed">{t(service.descKey)}</p>
                </div>
              </IntlLink>
            ))}
          </div>
        </div>

        {/* Quick actions row - Bookmarks, Notes, Spaces */}
        <div className="mb-12">
          <div className="flex items-center gap-3 mb-6">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
            <h2 className="text-xs font-semibold text-text-muted uppercase tracking-widest font-display">
              {t('quick_actions') || 'Quick Actions'}
            </h2>
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              {
                href: '/bookmarks',
                title: tNav('bookmarks'),
                icon: (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                ),
              },
              {
                href: '/notes',
                title: tNav('notes'),
                icon: (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                ),
              },
              {
                href: '/spaces',
                title: tNav('spaces'),
                icon: (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                  </svg>
                ),
              },
            ].map((action) => (
              <IntlLink key={action.href} href={action.href} className="group">
                <div className="flex items-center gap-3 bg-vault-900/40 border border-white/[0.06] rounded-xl px-4 py-3 transition-all duration-200 hover:border-white/[0.12] hover:bg-vault-900/60">
                  <div className="w-9 h-9 rounded-lg bg-vault-800 border border-white/[0.06] flex items-center justify-center text-text-muted group-hover:text-amber-400 group-hover:border-amber-500/20 transition-all duration-200">
                    {action.icon}
                  </div>
                  <span className="text-sm font-medium text-text-secondary group-hover:text-text-primary transition-colors">{action.title}</span>
                </div>
              </IntlLink>
            ))}
          </div>
        </div>

        {/* Journal - for admin/superuser */}
        {hasExtendedAccess && (
          <div className="mb-12">
            <IntlLink href="/journal" className="group block">
              <div className="bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-transparent border border-amber-500/10 rounded-2xl px-5 py-4 transition-all duration-200 hover:border-amber-500/20 hover:shadow-glow">
                <div className="flex items-center gap-4">
                  <div className="w-11 h-11 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
                    <svg className="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="font-semibold text-text-primary font-display">{tNav('journal')}</h3>
                    <p className="text-text-muted text-xs">{t('journal_desc')}</p>
                  </div>
                </div>
              </div>
            </IntlLink>
          </div>
        )}

        {/* Admin/Superuser Extended Section */}
        {hasExtendedAccess && (
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-6">
              <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
              <h2 className="text-xs font-semibold text-text-muted uppercase tracking-widest font-display flex items-center gap-2">
                <svg className="w-3.5 h-3.5 text-amber-400/60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                {t('admin_section_title')}
              </h2>
              <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <IntlLink href="/dashboard" className="group">
                <div className="bg-vault-900/40 border border-white/[0.06] rounded-xl p-4 transition-all duration-200 hover:border-white/[0.12] hover:bg-vault-900/60 h-full flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-vault-800 border border-white/[0.06] flex items-center justify-center text-text-muted group-hover:text-amber-400 transition-colors shrink-0">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="font-semibold text-text-primary text-sm font-display">{tNav('dashboard')}</h3>
                    <p className="text-text-muted text-xs">{t('dashboard_desc')}</p>
                  </div>
                </div>
              </IntlLink>

              {isAdmin && (
                <IntlLink href="/monitoring" className="group">
                  <div className="bg-vault-900/40 border border-white/[0.06] rounded-xl p-4 transition-all duration-200 hover:border-white/[0.12] hover:bg-vault-900/60 h-full flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-vault-800 border border-white/[0.06] flex items-center justify-center text-text-muted group-hover:text-amber-400 transition-colors shrink-0">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-semibold text-text-primary text-sm font-display">{tNav('monitoring')}</h3>
                      <p className="text-text-muted text-xs">{t('monitoring_desc')}</p>
                    </div>
                  </div>
                </IntlLink>
              )}

              {isAdmin && (
                <IntlLink href="/settings" className="group">
                  <div className="bg-vault-900/40 border border-white/[0.06] rounded-xl p-4 transition-all duration-200 hover:border-white/[0.12] hover:bg-vault-900/60 h-full flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-vault-800 border border-white/[0.06] flex items-center justify-center text-text-muted group-hover:text-amber-400 transition-colors shrink-0">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-semibold text-text-primary text-sm font-display">{tNav('settings')}</h3>
                      <p className="text-text-muted text-xs">{t('settings_desc')}</p>
                    </div>
                  </div>
                </IntlLink>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
