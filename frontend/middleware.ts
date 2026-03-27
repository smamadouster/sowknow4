import createMiddleware from 'next-intl/middleware';
import { NextRequest, NextResponse } from 'next/server';
import { routing } from './i18n/routing';

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

async function verifySession(request: NextRequest): Promise<boolean> {
  try {
    const response = await fetch(new URL('/api/v1/auth/me', request.url), {
      headers: {
        cookie: request.headers.get('cookie') || '',
      },
      credentials: 'include',
    });
    return response.ok;
  } catch {
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
    let locale = request.nextUrl.locale;
    if (!locale || locale === 'undefined') {
      locale = 'fr';
    }
    const loginUrl = new URL(`/${locale}/login`, request.url);
    loginUrl.searchParams.set('redirect', pathname);
    return Response.redirect(loginUrl);
  }
  
  return t(request);
}

export const config = {
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)']
};
