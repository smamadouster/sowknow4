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

  // Ensure that the incoming `locale` is valid
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) {
    notFound();
  }

  // Providing all messages to the client side
  const messages = await getMessages();
  const tNav = await getTranslations({ locale, namespace: 'nav' });

  return (
    <NextIntlClientProvider messages={messages}>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[100] focus:bg-white focus:text-blue-700 focus:px-4 focus:py-2 focus:rounded focus:shadow-lg focus:ring-2 focus:ring-blue-500"
      >
        {tNav('skip_to_content')}
      </a>
      <nav aria-label={tNav('main_navigation')} style={{ background: 'linear-gradient(135deg, #78350f, #92400e, #b45309)', color: 'white', padding: '12px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '1.5rem', letterSpacing: '0.05em' }}>SOWKNOW</h1>
          <p style={{ margin: '3px 0 0 0', opacity: 0.8, fontSize: '0.8rem' }}>Mon Coffre de Biens Digitaux</p>
        </div>
        <div style={{ marginTop: '0' }}>
          <LanguageSelector />
        </div>
      </nav>
      <Navigation />
      <main id="main-content">{children}</main>
      <footer style={{ marginTop: '50px', padding: '20px', background: '#fffbeb', textAlign: 'center', borderTop: '1px solid #fde68a' }}>
        <p style={{ color: '#92400e', fontSize: '0.85rem' }}>SOWKNOW - Mon Coffre de Biens Digitaux</p>
      </footer>
    </NextIntlClientProvider>
  );
}
