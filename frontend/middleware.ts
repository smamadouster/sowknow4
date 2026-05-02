import createMiddleware from 'next-intl/middleware';
import { NextRequest } from 'next/server';
import { routing } from './i18n/routing';

const ACCESS_TOKEN_COOKIE = 'access_token';

const t = createMiddleware({
  ...routing,
  localeDetection: true,
});

const publicPaths = [
  '/api/auth/login',
  '/api/auth/register',
  '/api/v1/auth/login',
  '/api/v1/auth/register',
  '/api/v1/auth/refresh',
  '/health',
  '/api/v1/status',
];

const authPaths = [
  '/login',
  '/register',
  '/forgot-password',
  '/verify-email',
];

/**
 * Check whether the request carries an access_token cookie.
 *
 * DESIGN DECISION: We do NOT verify the JWT signature in Edge Middleware.
 * Next.js middleware bundles env vars at build time, so baking JWT_SECRET
 * into the frontend image makes auth fragile: every secret rotation or
 * rebuild with a different env file breaks the entire app (users get
 * redirected to login even though their tokens are perfectly valid).
 *
 * Instead we treat the middleware as a lightweight UX gate:
 *  - Cookie present  → let the request through to the page shell
 *  - Cookie missing  → redirect to login
 *
 * The backend still cryptographically validates the token on every API
 * request, and the client-side API client handles 401 by attempting a
 * silent refresh or redirecting to login.
 */
function hasSessionCookie(request: NextRequest): boolean {
  return Boolean(request.cookies.get(ACCESS_TOKEN_COOKIE)?.value);
}

export default async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isPublicPath = publicPaths.some(path =>
    pathname === path || pathname.startsWith(path + '/')
  );

  const isAuthPage = authPaths.some(path => pathname.includes(path));

  if (isPublicPath || isAuthPage) {
    return t(request);
  }

  const hasCookie = hasSessionCookie(request);

  if (!hasCookie) {
    // Extract locale from path using routing config (not hardcoded list).
    // With localePrefix: 'as-needed', default locale has no prefix.
    const segments = pathname.split('/').filter(Boolean);
    const nonDefaultLocales = routing.locales.filter(l => l !== routing.defaultLocale);
    const pathLocale = nonDefaultLocales.includes(segments[0] as typeof routing.locales[number])
      ? segments[0]
      : '';
    const loginPath = pathLocale ? `/${pathLocale}/login` : '/login';
    const loginUrl = new URL(loginPath, request.url);
    loginUrl.searchParams.set('redirect', pathname);
    return Response.redirect(loginUrl);
  }

  return t(request);
}

export const config = {
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)']
};
