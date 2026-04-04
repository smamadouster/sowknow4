import createMiddleware from 'next-intl/middleware';
import { NextRequest } from 'next/server';
import { jwtVerify } from 'jose';
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
 * Verify the access_token JWT locally using HS256.
 * No backend HTTP call needed — just cryptographic signature check.
 */
async function verifySession(request: NextRequest): Promise<boolean> {
  const token = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!token) return false;

  const secret = process.env.JWT_SECRET;
  if (!secret) return false;

  try {
    const { payload } = await jwtVerify(
      token,
      new TextEncoder().encode(secret),
      { algorithms: ['HS256'] }
    );
    return payload.type === 'access' && typeof payload.sub === 'string';
  } catch {
    // Expired, tampered, or malformed token
    return false;
  }
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

  const hasValidSession = await verifySession(request);

  if (!hasValidSession) {
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
