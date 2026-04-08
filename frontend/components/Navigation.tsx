'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';
import { useState, useEffect, useRef } from 'react';
import { useAuthStore, useChatStore, useUploadStore } from '@/lib/store';
import { useSessionTimeout } from '@/hooks/useSessionTimeout';
import { useScrollDirection } from '@/hooks/useScrollDirection';
import MobileBottomSheet from '@/components/mobile/MobileBottomSheet';

type NavLabelKey =
  | 'home' | 'search' | 'documents' | 'chat' | 'collections' | 'smart_folders'
  | 'knowledge_graph' | 'dashboard' | 'monitoring' | 'settings' | 'journal'
  | 'bookmarks' | 'notes' | 'spaces';

interface NavItem {
  href: string;
  labelKey: NavLabelKey;
  icon: React.ReactNode;
  roles?: string[];
}

const navItems: NavItem[] = [
  {
    href: '/',
    labelKey: 'home',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
  },
  {
    href: '/search',
    labelKey: 'search',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
  },
  {
    href: '/documents',
    labelKey: 'documents',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    href: '/chat',
    labelKey: 'chat',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
      </svg>
    ),
  },
  {
    href: '/collections',
    labelKey: 'collections',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
  {
    href: '/smart-folders',
    labelKey: 'smart_folders',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
  {
    href: '/bookmarks',
    labelKey: 'bookmarks',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
      </svg>
    ),
  },
  {
    href: '/notes',
    labelKey: 'notes',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
    ),
  },
  {
    href: '/spaces',
    labelKey: 'spaces',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
      </svg>
    ),
  },
  {
    href: '/knowledge-graph',
    labelKey: 'knowledge_graph',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
      </svg>
    ),
  },
  {
    href: '/journal',
    labelKey: 'journal',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
];

const adminItems: NavItem[] = [
  {
    href: '/dashboard',
    labelKey: 'dashboard',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
  {
    href: '/monitoring',
    labelKey: 'monitoring',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    ),
    roles: ['admin'],
  },
  {
    href: '/settings',
    labelKey: 'settings',
    icon: (
      <svg className="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    roles: ['admin'],
  },
];

export function Navigation() {
  const t = useTranslations('nav');
  const tc = useTranslations('common');
  const pathname = usePathname();
  const locale = useLocale();
  const router = useRouter();
  const { logout, user, _hasHydrated } = useAuthStore();
  useSessionTimeout();
  const isStreaming = useChatStore((s) => s.isStreaming);
  const isUploading = useUploadStore((s) => s.isUploading);
  const userRole = user?.role || 'user';
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [moreSheetOpen, setMoreSheetOpen] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);

  const scrollDirection = useScrollDirection();

  const handleLogout = async () => {
    setShowLogoutConfirm(false);
    await logout();
    router.push(`/${locale}/login`);
  };

  useEffect(() => {
    setMoreSheetOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!showLogoutConfirm) return;
    const firstButton = modalRef.current?.querySelector<HTMLButtonElement>('button');
    firstButton?.focus();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowLogoutConfirm(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [showLogoutConfirm]);

  const mainItems = navItems.filter(item => !item.roles || item.roles.includes(userRole));
  const visibleAdminItems = adminItems.filter(item => !item.roles || item.roles.includes(userRole));

  const mobileTabHrefs = ['/search', '/documents', '/chat'];
  const mobileTabItems = mobileTabHrefs
    .map(href => navItems.find(item => item.href === href))
    .filter((item): item is NavItem => item !== undefined);
  const moreItems = mainItems.filter(item => !mobileTabHrefs.includes(item.href));

  const isActive = (href: string) => {
    if (href === '/') return pathname === `/${locale}` || pathname === `/${locale}/` || pathname === '/';
    return pathname === `/${locale}${href}` || pathname.startsWith(`/${locale}${href}/`);
  };

  return (
    <>
      {/* Desktop vertical sidebar */}
      <aside
        className={`hidden md:flex flex-col shrink-0 h-[calc(100vh-3.5rem)] sticky top-14 border-r border-white/[0.06] bg-vault-950/60 backdrop-blur-sm transition-all duration-300 ${
          isCollapsed ? 'w-16' : 'w-56'
        }`}
        aria-label={t('main_navigation')}
      >
        {/* Collapse toggle */}
        <div className={`flex items-center h-10 border-b border-white/[0.04] ${isCollapsed ? 'justify-center' : 'justify-end pr-2'}`}>
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            aria-label={t('toggle_navigation')}
            aria-expanded={!isCollapsed}
            className="p-1.5 rounded-lg text-text-muted hover:text-text-secondary hover:bg-white/[0.06] transition-all duration-200"
          >
            <svg className={`w-4 h-4 transition-transform duration-300 ${isCollapsed ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
          </button>
        </div>

        {/* Main nav items */}
        <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5 scrollbar-thin">
          {mainItems.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                title={isCollapsed ? t(item.labelKey) : undefined}
                className={`group relative flex items-center gap-2.5 rounded-lg transition-all duration-200 ${
                  isCollapsed ? 'justify-center px-0 py-2.5 mx-auto w-10' : 'px-3 py-2'
                } ${
                  active
                    ? 'bg-amber-500/10 text-amber-400'
                    : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.05]'
                }`}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-amber-400" />
                )}
                <span aria-hidden="true">{item.icon}</span>
                {!isCollapsed && (
                  <span className="text-[13px] font-medium truncate">{t(item.labelKey)}</span>
                )}
              </Link>
            );
          })}

          {/* Admin section */}
          {visibleAdminItems.length > 0 && (
            <>
              <div className={`pt-3 pb-1 ${isCollapsed ? 'px-0' : 'px-3'}`}>
                <div className="border-t border-white/[0.06]" />
                {!isCollapsed && (
                  <p className="text-[10px] font-semibold text-text-muted/60 uppercase tracking-widest mt-2">
                    Admin
                  </p>
                )}
              </div>
              {visibleAdminItems.map((item) => {
                const active = isActive(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    title={isCollapsed ? t(item.labelKey) : undefined}
                    className={`group relative flex items-center gap-2.5 rounded-lg transition-all duration-200 ${
                      isCollapsed ? 'justify-center px-0 py-2.5 mx-auto w-10' : 'px-3 py-2'
                    } ${
                      active
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.05]'
                    }`}
                  >
                    {active && (
                      <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-amber-400" />
                    )}
                    <span aria-hidden="true">{item.icon}</span>
                    {!isCollapsed && (
                      <span className="text-[13px] font-medium truncate">{t(item.labelKey)}</span>
                    )}
                  </Link>
                );
              })}
            </>
          )}
        </nav>

        {/* Bottom: logout */}
        <div className="border-t border-white/[0.06] p-2">
          <button
            onClick={() => setShowLogoutConfirm(true)}
            aria-label={t('logout')}
            title={isCollapsed ? t('logout') : undefined}
            className={`flex items-center gap-2.5 w-full rounded-lg text-text-muted hover:text-red-400 hover:bg-red-500/5 transition-all duration-200 ${
              isCollapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2'
            }`}
          >
            <svg className="w-[18px] h-[18px] shrink-0" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            {!isCollapsed && (
              <span className="text-[13px] font-medium">{t('logout')}</span>
            )}
          </button>
        </div>
      </aside>

      {/* Mobile bottom navigation */}
      <nav
        className={`md:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-white/[0.06] bg-vault-950/95 backdrop-blur-xl pb-safe px-safe transition-transform duration-300 ${
          scrollDirection === 'down' ? 'translate-y-full' : 'translate-y-0'
        }`}
        aria-label={t('main_navigation')}
      >
        <div className="flex items-stretch justify-around h-14 px-1">
          {mobileTabItems.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={`relative flex flex-col items-center justify-center gap-0.5 min-w-[64px] min-h-[44px] px-2 py-1 rounded-lg transition-all ${
                  active ? 'text-amber-400' : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                {active && (
                  <span className="absolute top-1.5 left-1/2 -translate-x-1/2 w-6 h-1 rounded-full bg-amber-400/80" aria-hidden="true" />
                )}
                <span aria-hidden="true" className="mt-2">{item.icon}</span>
                <span className="text-[10px] font-medium whitespace-nowrap">{t(item.labelKey)}</span>
              </Link>
            );
          })}

          {/* More button */}
          <button
            onClick={() => setMoreSheetOpen(true)}
            aria-label={t('toggle_navigation')}
            aria-expanded={moreSheetOpen}
            className="relative flex flex-col items-center justify-center gap-0.5 min-w-[64px] min-h-[44px] px-2 py-1 rounded-lg text-text-muted hover:text-text-secondary transition-all"
          >
            <svg className="w-[18px] h-[18px] mt-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            <span className="text-[10px] font-medium">Plus</span>
          </button>
        </div>
      </nav>

      {/* Mobile More — bottom sheet */}
      <MobileBottomSheet
        open={moreSheetOpen}
        onClose={() => setMoreSheetOpen(false)}
        title="Navigation"
        heightPercent={65}
      >
        <nav aria-label={t('main_navigation')}>
          {moreItems.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                onClick={() => setMoreSheetOpen(false)}
                className={`flex items-center gap-3 px-2 py-3 rounded-xl text-sm font-medium transition-all ${
                  active
                    ? 'bg-amber-500/10 text-amber-400'
                    : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
                }`}
              >
                {active && (
                  <span className="w-1 h-5 rounded-full bg-amber-400 shrink-0" aria-hidden="true" />
                )}
                <span aria-hidden="true">{item.icon}</span>
                <span>{t(item.labelKey)}</span>
              </Link>
            );
          })}

          {/* Admin section in More sheet */}
          {visibleAdminItems.length > 0 && (
            <>
              <div className="px-2 pt-3 pb-1">
                <div className="border-t border-white/[0.06]" />
                <p className="text-[10px] font-semibold text-text-muted/60 uppercase tracking-widest mt-2">
                  Admin
                </p>
              </div>
              {visibleAdminItems.map((item) => {
                const active = isActive(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    onClick={() => setMoreSheetOpen(false)}
                    className={`flex items-center gap-3 px-2 py-3 rounded-xl text-sm font-medium transition-all ${
                      active
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
                    }`}
                  >
                    {active && (
                      <span className="w-1 h-5 rounded-full bg-amber-400 shrink-0" aria-hidden="true" />
                    )}
                    <span aria-hidden="true">{item.icon}</span>
                    <span>{t(item.labelKey)}</span>
                  </Link>
                );
              })}
            </>
          )}
        </nav>

        {/* Logout in More sheet */}
        <div className="border-t border-white/[0.06] pt-3 mt-1">
          <button
            onClick={() => { setMoreSheetOpen(false); setShowLogoutConfirm(true); }}
            className="flex items-center gap-3 w-full px-2 py-3 rounded-xl text-sm font-medium text-text-muted hover:text-red-400 hover:bg-red-500/5 transition-all"
          >
            <svg className="w-[18px] h-[18px] shrink-0" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            <span>{t('logout')}</span>
          </button>
        </div>
      </MobileBottomSheet>

      {/* Logout confirmation modal */}
      {showLogoutConfirm && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShowLogoutConfirm(false)}
          aria-hidden="true"
        >
          <div
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="logout-dialog-title"
            className="bg-vault-900 border border-white/[0.08] rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center">
                <svg className="w-5 h-5 text-red-400" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </div>
              <p id="logout-dialog-title" className="text-text-primary font-medium font-display">{t('logout_confirm')}</p>
            </div>
            {isStreaming && (
              <div className="mb-3 flex items-start gap-2 bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-2.5">
                <svg className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                </svg>
                <p className="text-sm text-amber-300">{t('logout_streaming_warning')}</p>
              </div>
            )}
            {isUploading && (
              <div className="mb-3 flex items-start gap-2 bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-2.5">
                <svg className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                <p className="text-sm text-amber-300">{t('logout_upload_warning')}</p>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowLogoutConfirm(false)}
                className="px-4 py-2 rounded-xl text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-white/[0.04] transition-all"
              >
                {tc('cancel')}
              </button>
              <button
                onClick={handleLogout}
                className="px-4 py-2 rounded-xl text-sm font-medium text-white bg-red-500/90 hover:bg-red-500 transition-all shadow-lg shadow-red-500/20"
              >
                {t('logout')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default Navigation;
