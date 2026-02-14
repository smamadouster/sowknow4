import '../globals.css';
import { NextIntlClientProvider } from 'next-intl';
import { getMessages } from 'next-intl/server';
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
  if (!routing.locales.includes(locale as any)) {
    notFound();
  }

  // Providing all messages to the client side
  const messages = await getMessages();

  return (
    <html lang={locale}>
      <body style={{ margin: 0, padding: 0, fontFamily: 'Arial, sans-serif' }}>
        <NextIntlClientProvider messages={messages}>
          <nav style={{ background: '#1f2937', color: 'white', padding: '12px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h1 style={{ margin: 0, fontSize: '1.5rem' }}>SOWKNOW4</h1>
              <p style={{ margin: '3px 0 0 0', opacity: 0.8, fontSize: '0.8rem' }}>Multi-Generational Legacy Knowledge System</p>
            </div>
            <div style={{ marginTop: '0' }}>
              <LanguageSelector />
            </div>
          </nav>
          <Navigation />
          <main>{children}</main>
          <footer style={{ marginTop: '50px', padding: '20px', background: '#f5f5f5', textAlign: 'center' }}>
            <p>SOWKNOW4 - Phase 3: Multi-Agent Search | Production</p>
          </footer>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
