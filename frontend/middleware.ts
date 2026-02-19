import createMiddleware from 'next-intl/middleware';
import { routing } from './i18n/routing';

const t = createMiddleware({
  ...routing,
  localeDetection: true,
});

export default function middleware(request: any) {
  const { pathname } = request.nextUrl;
  
  const publicPaths = [
    '/api/auth/login',
    '/api/auth/register',
    '/api/v1/auth/login',
    '/api/v1/auth/register',
    '/health',
    '/api/v1/status',
  ];
  
  const isPublicPath = publicPaths.some(path => 
    pathname === path || pathname.startsWith(path + '/')
  );
  
  const isAuthPage = pathname.includes('/login') || pathname.includes('/register');
  
  const accessToken = request.cookies.get('access_token');
  const refreshToken = request.cookies.get('refresh_token');
  
  if (!accessToken && !refreshToken) {
    if (!isPublicPath && !isAuthPage) {
      let locale = request.nextUrl.locale;
      if (!locale || locale === 'undefined') {
        locale = 'fr';
      }
      const loginUrl = new URL(`/${locale}/login`, request.url);
      return Response.redirect(loginUrl);
    }
  }
  
  return t(request);
}

export const config = {
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)']
};
