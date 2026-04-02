'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Link as IntlLink } from '@/i18n/routing';
import { useAuthStore } from '@/lib/store';

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

  return (
    <div className="min-h-[calc(100vh-180px)] bg-gradient-to-br from-amber-50 via-orange-50 to-yellow-50">
      {/* Welcome Hero */}
      <div className="max-w-5xl mx-auto px-4 pt-12 pb-8">
        <div className="text-center mb-10">
          {userName && (
            <p className="text-lg text-amber-700 mb-2 font-medium">
              {t('hello', { name: userName })}
            </p>
          )}
          <h1 className="text-3xl md:text-4xl font-bold text-gray-900 mb-6 leading-tight">
            {t('welcome_title')}
          </h1>
          <div className="max-w-2xl mx-auto bg-white/80 backdrop-blur-sm rounded-2xl shadow-sm border border-amber-200/60 px-6 py-5">
            <p className="text-gray-700 text-lg leading-relaxed italic">
              {t('welcome_message')}
            </p>
            <p className="text-amber-600 font-semibold text-xl mt-3 tracking-wide">
              {t('welcome_discovery')}
            </p>
          </div>
        </div>

        {/* Main Services Grid */}
        <div className="mb-10">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4 px-1">
            {t('services_title')}
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <IntlLink href="/search" className="group">
              <div className="bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-gray-200 hover:border-blue-300 h-full flex flex-col items-center text-center">
                <div className="w-14 h-14 bg-blue-100 rounded-xl flex items-center justify-center mb-3 group-hover:bg-blue-200 transition-colors">
                  <svg className="w-7 h-7 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{tNav('search')}</h3>
                <p className="text-gray-500 text-xs leading-relaxed">{t('search_desc')}</p>
              </div>
            </IntlLink>

            <IntlLink href="/documents" className="group">
              <div className="bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-gray-200 hover:border-emerald-300 h-full flex flex-col items-center text-center">
                <div className="w-14 h-14 bg-emerald-100 rounded-xl flex items-center justify-center mb-3 group-hover:bg-emerald-200 transition-colors">
                  <svg className="w-7 h-7 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{tNav('documents')}</h3>
                <p className="text-gray-500 text-xs leading-relaxed">{t('documents_desc')}</p>
              </div>
            </IntlLink>

            <IntlLink href="/chat" className="group">
              <div className="bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-gray-200 hover:border-violet-300 h-full flex flex-col items-center text-center">
                <div className="w-14 h-14 bg-violet-100 rounded-xl flex items-center justify-center mb-3 group-hover:bg-violet-200 transition-colors">
                  <svg className="w-7 h-7 text-violet-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                  </svg>
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{tNav('chat')}</h3>
                <p className="text-gray-500 text-xs leading-relaxed">{t('chat_desc')}</p>
              </div>
            </IntlLink>

            <IntlLink href="/collections" className="group">
              <div className="bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-gray-200 hover:border-sky-300 h-full flex flex-col items-center text-center">
                <div className="w-14 h-14 bg-sky-100 rounded-xl flex items-center justify-center mb-3 group-hover:bg-sky-200 transition-colors">
                  <svg className="w-7 h-7 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                  </svg>
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{tNav('collections')}</h3>
                <p className="text-gray-500 text-xs leading-relaxed">{t('collections_desc')}</p>
              </div>
            </IntlLink>

            <IntlLink href="/smart-folders" className="group">
              <div className="bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-gray-200 hover:border-teal-300 h-full flex flex-col items-center text-center">
                <div className="w-14 h-14 bg-teal-100 rounded-xl flex items-center justify-center mb-3 group-hover:bg-teal-200 transition-colors">
                  <svg className="w-7 h-7 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                  </svg>
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{tNav('smart_folders')}</h3>
                <p className="text-gray-500 text-xs leading-relaxed">{t('smart_folders_desc')}</p>
              </div>
            </IntlLink>

            <IntlLink href="/knowledge-graph" className="group">
              <div className="bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-gray-200 hover:border-purple-300 h-full flex flex-col items-center text-center">
                <div className="w-14 h-14 bg-purple-100 rounded-xl flex items-center justify-center mb-3 group-hover:bg-purple-200 transition-colors">
                  <svg className="w-7 h-7 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{tNav('knowledge_graph')}</h3>
                <p className="text-gray-500 text-xs leading-relaxed">{t('knowledge_graph_desc')}</p>
              </div>
            </IntlLink>
          </div>
        </div>

        {/* Journal - for admin/superuser */}
        {hasExtendedAccess && (
          <div className="mb-10">
            <IntlLink href="/journal" className="group block">
              <div className="bg-white rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-gray-200 hover:border-amber-300 flex items-center gap-4">
                <div className="w-12 h-12 bg-amber-100 rounded-xl flex items-center justify-center group-hover:bg-amber-200 transition-colors shrink-0">
                  <svg className="w-6 h-6 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{tNav('journal')}</h3>
                  <p className="text-gray-500 text-xs">{t('journal_desc')}</p>
                </div>
              </div>
            </IntlLink>
          </div>
        )}

        {/* Admin/Superuser Extended Section */}
        {hasExtendedAccess && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4 px-1 flex items-center gap-2">
              <svg className="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              {t('admin_section_title')}
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <IntlLink href="/dashboard" className="group">
                <div className="bg-gradient-to-br from-slate-50 to-slate-100 rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-slate-200 hover:border-slate-400 h-full flex items-center gap-4">
                  <div className="w-12 h-12 bg-slate-200 rounded-xl flex items-center justify-center group-hover:bg-slate-300 transition-colors shrink-0">
                    <svg className="w-6 h-6 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                    </svg>
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900">{tNav('dashboard')}</h3>
                    <p className="text-gray-500 text-xs">{t('dashboard_desc')}</p>
                  </div>
                </div>
              </IntlLink>

              {isAdmin && (
                <IntlLink href="/monitoring" className="group">
                  <div className="bg-gradient-to-br from-slate-50 to-slate-100 rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-slate-200 hover:border-slate-400 h-full flex items-center gap-4">
                    <div className="w-12 h-12 bg-slate-200 rounded-xl flex items-center justify-center group-hover:bg-slate-300 transition-colors shrink-0">
                      <svg className="w-6 h-6 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900">{tNav('monitoring')}</h3>
                      <p className="text-gray-500 text-xs">{t('monitoring_desc')}</p>
                    </div>
                  </div>
                </IntlLink>
              )}

              {isAdmin && (
                <IntlLink href="/settings" className="group">
                  <div className="bg-gradient-to-br from-slate-50 to-slate-100 rounded-xl shadow-sm hover:shadow-md transition-all p-5 border border-slate-200 hover:border-slate-400 h-full flex items-center gap-4">
                    <div className="w-12 h-12 bg-slate-200 rounded-xl flex items-center justify-center group-hover:bg-slate-300 transition-colors shrink-0">
                      <svg className="w-6 h-6 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900">{tNav('settings')}</h3>
                      <p className="text-gray-500 text-xs">{t('settings_desc')}</p>
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
