import './globals.css';
import { NextIntlClientProvider } from 'next-intl';
import { getMessages } from 'next-intl/server';
import { notFound } from 'next/navigation';

export const metadata = {
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'default',
    title: 'SOWKNOW',
  },
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: '16x16 32x32 48x48', type: 'image/x-icon' },
      { url: '/icons/icon-96x96.png', sizes: '96x96', type: 'image/png' },
      { url: '/icons/icon-192x192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icons/icon-512x512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [
      { url: '/icons/apple-touch-icon.png', sizes: '180x180', type: 'image/png' },
    ],
  },
};

if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// Define supported locales
const locales = ['fr', 'en'];

export default async function RootLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale?: string }>;
}) {
  // Get locale from params or default to 'fr'
  const { locale } = await params;
  const validatedLocale = locale && locales.includes(locale) ? locale : 'fr';

  // Get messages for the current locale
  let messages;
  try {
    messages = await getMessages();
  } catch (error) {
    notFound();
  }

  return (
    <html lang={validatedLocale}>
      <body style={{ margin: 0, padding: 0, fontFamily: 'Arial, sans-serif' }}>
        <NextIntlClientProvider messages={messages}>
          <nav style={{ background: '#333', color: 'white', padding: '20px' }}>
            <h1 style={{ margin: 0 }}>SOWKNOW4</h1>
            <p style={{ margin: '5px 0 0 0', opacity: 0.8 }}>Multi-Generational Legacy Knowledge System</p>
          </nav>
          <main>{children}</main>
          <footer style={{ marginTop: '50px', padding: '20px', background: '#f5f5f5', textAlign: 'center' }}>
            <p>SOWKNOW4 - Phase 3: Multi-Agent Search | Production</p>
          </footer>
        </NextIntlClientProvider>
      </body>
    </html>
  )
}
