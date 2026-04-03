'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';
import { useState, useEffect, useRef } from 'react';
import { useAuthStore, useChatStore, useUploadStore } from '@/lib/store';
import { useSessionTimeout } from '@/hooks/useSessionTimeout';

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
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
  },
  {
    href: '/search',
    labelKey: 'search',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
  },
  {
    href: '/documents',
    labelKey: 'documents',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    href: '/chat',
    labelKey: 'chat',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
      </svg>
    ),
  },
  {
    href: '/collections',
    labelKey: 'collections',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
  {
    href: '/smart-folders',
    labelKey: 'smart_folders',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
  {
    href: '/bookmarks',
    labelKey: 'bookmarks' as NavLabelKey,
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
      </svg>
    ),
  },
  {
    href: '/notes',
    labelKey: 'notes' as NavLabelKey,
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
    ),
  },
  {
    href: '/spaces',
    labelKey: 'spaces' as NavLabelKey,
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
  {
    href: '/knowledge-graph',
    labelKey: 'knowledge_graph',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
      </svg>
    ),
  },
  {
    href: '/journal',
    labelKey: 'journal',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
  {
    href: '/monitoring',
    labelKey: 'monitoring',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    ),
    roles: ['admin'],
  },
  {
    href: '/settings',
    labelKey: 'settings',
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
  const [activeTab, setActiveTab] = useState<'all' | 'admin'>('all');
  const userRole = user?.role || 'user';
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  const mobileMenuRef = useRef<HTMLDivElement>(null);

  const handleLogout = async () => {
    setShowLogoutConfirm(false);
    await logout();
    router.push(`/${locale}/login`);
  };

  useEffect(() => {
    setIsMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!isMobileOpen) return;

    const firstLink = mobileMenuRef.current?.querySelector<HTMLElement>('a, button');
    firstLink?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsMobileOpen(false);
        return;
      }
      if (e.key === 'Tab') {
        const focusable = mobileMenuRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled])'
        );
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isMobileOpen]);

  useEffect(() => {
    if (isMobileOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [isMobileOpen]);

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

  const allItems = [...navItems, ...adminItems];

  const filteredItems = activeTab === 'admin'
    ? allItems.filter(item => item.roles?.includes(userRole))
    : navItems.filter(item => !item.roles || item.roles.includes(userRole));

  const mobileItems = activeTab === 'admin'
    ? allItems.filter(item => item.roles?.includes(userRole))
    : navItems.filter(item => !item.roles || item.roles.includes(userRole));

  return (
    <>
      {/* Desktop navigation bar */}
      <nav className="hidden md:block border-b border-white/[0.06] bg-vault-950/40 backdrop-blur-sm" aria-label={t('main_navigation')}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-11">
            {/* Tab switcher */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => setActiveTab('all')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
                  activeTab === 'all'
                    ? 'bg-vault-800 text-amber-400 shadow-sm'
                    : 'text-text-muted hover:text-text-secondary hover:bg-white/[0.04]'
                }`}
              >
                {t('all_users') || 'All Users'}
              </button>
              {(userRole === 'admin' || userRole === 'superuser') && (
                <button
                  onClick={() => setActiveTab('admin')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
                    activeTab === 'admin'
                      ? 'bg-vault-800 text-amber-400 shadow-sm'
                      : 'text-text-muted hover:text-text-secondary hover:bg-white/[0.04]'
                  }`}
                >
                  {t('admin_only') || 'Admin Only'}
                </button>
              )}
            </div>

            {/* Nav links */}
            <div className="flex items-center gap-0.5">
              {filteredItems.map((item) => {
                const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                      isActive
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
                    }`}
                  >
                    <span aria-hidden="true">{item.icon}</span>
                    <span>{t(item.labelKey)}</span>
                  </Link>
                );
              })}
            </div>

            {/* Right side actions */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => setShowLogoutConfirm(true)}
                aria-label={t('logout')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-text-muted hover:text-red-400 hover:bg-red-500/5 transition-all duration-200"
              >
                <svg className="w-[18px] h-[18px]" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
              <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                aria-label={t('toggle_navigation')}
                aria-expanded={!isCollapsed}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-secondary hover:bg-white/[0.04] transition-all duration-200"
              >
                <svg className="w-[18px] h-[18px]" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
            </div>
          </div>

          {/* Collapsible second row */}
          {!isCollapsed && filteredItems.length > 8 && (
            <div className="flex items-center gap-0.5 pb-2 overflow-x-auto">
              {filteredItems.slice(8).map((item) => {
                const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-all duration-200 ${
                      isActive
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'text-text-muted hover:text-text-secondary hover:bg-white/[0.04]'
                    }`}
                  >
                    <span aria-hidden="true">{item.icon}</span>
                    <span>{t(item.labelKey)}</span>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </nav>

      {/* Mobile bottom navigation */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-white/[0.06] bg-vault-950/95 backdrop-blur-xl" aria-label={t('main_navigation')}>
        <div className="flex items-center justify-around h-14 px-2">
          {navItems.slice(0, 5).map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? 'page' : undefined}
                className={`flex flex-col items-center justify-center gap-0.5 px-2 py-1 rounded-lg min-w-[56px] transition-all ${
                  isActive
                    ? 'text-amber-400'
                    : 'text-text-muted'
                }`}
              >
                <span aria-hidden="true">{item.icon}</span>
                <span className="text-[10px] font-medium truncate max-w-[64px]">{t(item.labelKey)}</span>
              </Link>
            );
          })}
          {/* More button */}
          <button
            onClick={() => setIsMobileOpen(true)}
            aria-label={t('toggle_navigation')}
            className="flex flex-col items-center justify-center gap-0.5 px-2 py-1 rounded-lg min-w-[56px] text-text-muted"
          >
            <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            <span className="text-[10px] font-medium">More</span>
          </button>
        </div>
      </nav>

      {/* Mobile slide-in drawer */}
      <div
        className={`fixed inset-0 z-50 bg-black/60 backdrop-blur-sm md:hidden transition-opacity duration-300 ${
          isMobileOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
        onClick={() => setIsMobileOpen(false)}
        aria-hidden="true"
      />

      <div
        id="mobile-menu"
        ref={mobileMenuRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('main_navigation')}
        aria-hidden={!isMobileOpen}
        className={`fixed inset-y-0 right-0 z-50 w-72 bg-vault-950 border-l border-white/[0.06] shadow-2xl transform transition-transform duration-300 ease-in-out md:hidden ${
          isMobileOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Drawer header */}
        <div className="flex items-center justify-between px-4 py-4 border-b border-white/[0.06]">
          <span className="text-base font-semibold text-text-primary font-display">Navigation</span>
          <button
            onClick={() => setIsMobileOpen(false)}
            aria-label={t('close_menu')}
            className="p-2 rounded-lg text-text-muted hover:text-text-secondary hover:bg-white/[0.04] transition-all"
          >
            <svg className="w-5 h-5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Mobile tab switcher */}
        {(userRole === 'admin' || userRole === 'superuser') && (
          <div className="flex gap-1 p-3 border-b border-white/[0.06]">
            <button
              onClick={() => setActiveTab('all')}
              className={`flex-1 py-2 text-xs font-medium rounded-lg transition-all ${
                activeTab === 'all'
                  ? 'bg-vault-800 text-amber-400'
                  : 'text-text-muted hover:bg-white/[0.04]'
              }`}
            >
              {t('all_users')}
            </button>
            <button
              onClick={() => setActiveTab('admin')}
              className={`flex-1 py-2 text-xs font-medium rounded-lg transition-all ${
                activeTab === 'admin'
                  ? 'bg-vault-800 text-amber-400'
                  : 'text-text-muted hover:bg-white/[0.04]'
              }`}
            >
              {t('admin_only')}
            </button>
          </div>
        )}

        {/* Mobile nav links */}
        <nav className="py-2 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 200px)' }}>
          {mobileItems.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? 'page' : undefined}
                className={`flex items-center gap-3 px-4 py-3 text-sm font-medium transition-all ${
                  isActive
                    ? 'bg-amber-500/10 text-amber-400 border-r-2 border-amber-400'
                    : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
                }`}
              >
                <span aria-hidden="true">{item.icon}</span>
                <span>{t(item.labelKey)}</span>
              </Link>
            );
          })}
        </nav>

        {/* Mobile logout button */}
        <div className="border-t border-white/[0.06] p-4">
          <button
            onClick={() => { setIsMobileOpen(false); setShowLogoutConfirm(true); }}
            className="flex items-center gap-2 w-full px-3 py-2.5 rounded-xl text-sm font-medium text-text-muted hover:text-red-400 hover:bg-red-500/5 transition-all"
          >
            <svg className="w-5 h-5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            <span>{t('logout')}</span>
          </button>
        </div>
      </div>

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
