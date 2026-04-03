import { NextIntlClientProvider } from 'next-intl';
import { getMessages, getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';
import { LanguageSelector } from '@/components/LanguageSelector';
import Navigation from '@/components/Navigation';

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) {
    notFound();
  }

  const messages = await getMessages();
  const tNav = await getTranslations({ locale, namespace: 'nav' });

  return (
    <NextIntlClientProvider messages={messages}>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[100] focus:bg-vault-800 focus:text-amber-400 focus:px-4 focus:py-2 focus:rounded focus:shadow-lg focus:ring-2 focus:ring-amber-500"
      >
        {tNav('skip_to_content')}
      </a>

      {/* Top header bar */}
      <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-vault-1000/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-14">
            {/* Logo & branding */}
            <div className="flex items-center gap-3">
              <div className="relative">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center shadow-lg shadow-amber-500/20">
                  <svg className="w-5 h-5 text-vault-1000" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 2L2 7l10 5 10-5-10-5z" />
                    <path d="M2 17l10 5 10-5" />
                    <path d="M2 12l10 5 10-5" />
                  </svg>
                </div>
                <div className="absolute -inset-1 rounded-lg bg-amber-500/20 blur-sm -z-10" />
              </div>
              <div>
                <h1 className="text-base font-semibold text-text-primary tracking-tight font-display">SOWKNOW</h1>
                <p className="text-[10px] text-text-muted -mt-0.5 tracking-widest uppercase">Digital Vault</p>
              </div>
            </div>

            {/* Right side */}
            <div className="flex items-center gap-2">
              <LanguageSelector />
            </div>
          </div>
        </div>
      </header>

      <Navigation />

      <main id="main-content" className="min-h-[calc(100vh-8rem)]">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-white/[0.06] bg-vault-950/50 mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-md bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center">
                <svg className="w-3 h-3 text-vault-1000" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2L2 7l10 5 10-5-10-5z" />
                  <path d="M2 17l10 5 10-5" />
                  <path d="M2 12l10 5 10-5" />
                </svg>
              </div>
              <span className="text-xs text-text-muted">SOWKNOW — Your Digital Legacy Vault</span>
            </div>
            <p className="text-xs text-text-muted/60">Privacy-first. Zero cloud PII. Always encrypted.</p>
          </div>
        </div>
      </footer>
    </NextIntlClientProvider>
  );
}
