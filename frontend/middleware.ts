import createMiddleware from 'next-intl/middleware';
import { routing } from './i18n/routing';

export default createMiddleware({
  ...routing,
  // Add locale detection from cookie
  localeDetection: true,
});

export const config = {
  // Match all pathnames except for
  // - api routes
  // - _next (Next.js internals)
  // - static files (images, fonts, etc.)
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)']
};
