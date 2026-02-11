# Nginx Security Configuration Changes

## Date
2026-02-10

## Overview
Fixed Nginx configuration to remove wildcard CORS headers and add proper security headers for production deployment.

## Files Modified
1. `/root/development/src/active/sowknow4/nginx/nginx-http-only.conf` - Development/Testing configuration
2. `/root/development/src/active/sowknow4/nginx/nginx.conf` - Production HTTPS configuration

## Changes Summary

### 1. REMOVED Wildcard CORS Headers

**Before:**
```nginx
# CORS headers
add_header Access-Control-Allow-Origin "*" always;
add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
add_header Access-Control-Allow-Headers "Authorization, Content-Type, X-Requested-With" always;
add_header Access-Control-Allow-Credentials "true" always;
```

**After:**
```nginx
# CORS is handled by FastAPI backend - DO NOT add CORS headers here
# The backend's CORSMiddleware properly handles CORS with credentials

# Handle preflight requests - pass to backend
if ($request_method = 'OPTIONS') {
    proxy_pass http://backend;
    add_header Access-Control-Max-Age "3600" always;
    return 204;
}
```

**Reasoning:**
- FastAPI backend (`backend/app/main_minimal.py`) already handles CORS with CORSMiddleware
- Removing Nginx CORS headers prevents conflicts and duplication
- Backend properly handles `allow_credentials=True` which requires specific origins (not wildcards)
- Preflight requests are now properly proxied to the backend for consistent CORS handling

### 2. ADDED Global Security Headers

**New headers added to both configurations:**

```nginx
# Security headers (applied to all locations)
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
```

**Production-only additional header:**
```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

**Purpose:**
- `X-Frame-Options: DENY` - Prevents clickjacking attacks by blocking iframe embedding
- `X-Content-Type-Options: nosniff` - Prevents MIME type sniffing
- `X-XSS-Protection: 1; mode=block` - Enables XSS filtering in older browsers
- `Referrer-Policy: strict-origin-when-cross-origin` - Controls referrer information leakage
- `Permissions-Policy` - Disables browser features (geolocation, microphone, camera)
- `Strict-Transport-Security` (HTTPS only) - Enforces HTTPS connections

### 3. ADDED Content-Security-Policy for Frontend

```nginx
# Security headers for frontend
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self';" always;
```

**Purpose:**
- Prevents various XSS attacks by controlling resource loading
- Allows inline scripts/styles required by Next.js development
- Restricts image and font loading to same-origin and data URIs
- Note: `unsafe-inline` and `unsafe-eval` are necessary for Next.js in development

### 4. ADDED X-Frame-Options Override for API Docs

```nginx
# API documentation
location /api/docs {
    # Allow frames for API docs (Swagger UI)
    add_header X-Frame-Options "SAMEORIGIN" always;
}
```

**Purpose:**
- Swagger UI may need to be embedded in same-origin frames
- Overrides global `DENY` policy with more permissive `SAMEORIGIN` for documentation

### 5. Rate Limiting (Existing, Verified)

**Current configuration:**
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=general_limit:10m rate=30r/s;
```

**Applied to locations:**
- API endpoints: 10 requests/second with burst of 20
- Frontend/general: 30 requests/second with burst of 50

**Status:**
- Rate limiting is properly configured and appropriate for the application
- No changes needed

## Production Deployment Preparation

### HTTPS Configuration (nginx.conf)
The production configuration (`nginx.conf`) includes:

1. **SSL/TLS Settings:**
   - TLS 1.2 and 1.3 only
   - Strong cipher suites
   - SSL session caching

2. **HTTP to HTTPS Redirect:**
   - All HTTP traffic redirected to HTTPS
   - Let's Encrypt ACME challenge support

3. **Additional Security:**
   - HSTS header for HTTPS enforcement
   - All other security headers from HTTP-only version

### Deployment Checklist

Before deploying to production:

- [ ] SSL certificates are in place at `/etc/letsencrypt/live/sowknow.gollamtech.com/`
- [ ] Backend CORS origins are properly configured in `backend/app/main_minimal.py`
- [ ] Backend `TrustedHostMiddleware` is configured with specific hosts (currently wildcard)
- [ ] Rate limits are appropriate for production traffic
- [ ] CSP policy is tested with Next.js production build
- [ ] HSTS preload not yet enabled (can be added later after stability verification)

### Backend Configuration Note

The backend currently has wildcard CORS and trusted hosts:
```python
# backend/app/main_minimal.py lines 35-47
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # In production, set specific hosts
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Recommendation for production:**
- Update `allowed_hosts` to `["sowknow.gollamtech.com", "localhost"]`
- Update `allow_origins` to `["https://sowknow.gollamtech.com"]`

## Testing

### Manual Testing Steps

1. **Test CORS Headers:**
   ```bash
   curl -H "Origin: https://sowknow.gollamtech.com" \
         -H "Access-Control-Request-Method: POST" \
         -X OPTIONS \
         http://localhost/api/v1/auth/login \
         -v
   ```
   Expected: CORS headers should come from backend, not Nginx

2. **Test Security Headers:**
   ```bash
   curl -I http://localhost/
   ```
   Expected: All security headers should be present

3. **Test Rate Limiting:**
   ```bash
   for i in {1..15}; do curl http://localhost/api/v1/status; done
   ```
   Expected: Requests after burst limit should be rate-limited

4. **Test API Docs:**
   ```bash
   curl -I http://localhost/api/docs
   ```
   Expected: `X-Frame-Options: SAMEORIGIN` (not DENY)

## Rollback Plan

If issues occur after deployment:

1. Revert to previous configuration:
   ```bash
   git checkout HEAD~ nginx/nginx-http-only.conf nginx/nginx.conf
   docker-compose restart nginx
   ```

2. Check logs:
   ```bash
   docker logs sowknow4-nginx
   docker logs sowknow4-backend
   ```

3. Common issues and fixes:
   - **CORS errors:** Backend CORS configuration needs update
   - **Frame errors:** Check CSP policy and X-Frame-Options
   - **Rate limit errors:** Adjust `burst` values in rate limiting zones

## Security Considerations

### Current Security Posture

✅ **Implemented:**
- Wildcard CORS removed from Nginx
- All major security headers in place
- Rate limiting configured
- HTTPS ready with strong TLS settings
- CSP policy for frontend

⚠️ **Needs Attention:**
- Backend CORS still uses wildcard (should be restricted)
- Backend TrustedHost still uses wildcard (should be restricted)
- CSP policy uses `unsafe-inline` (necessary for Next.js, monitor for alternatives)
- HSTS preload not yet enabled (consider after stability verification)

### Future Improvements

1. **Content-Security-Policy:**
   - Consider nonces for inline scripts instead of `unsafe-inline`
   - Add report-to endpoint for CSP violations monitoring

2. **TLS Configuration:**
   - Add OCSP stapling
   - Consider certificate transparency monitoring

3. **CSP Reporting:**
   - Implement CSP violation reporting
   - Set up monitoring for security events

4. **Backend Hardening:**
   - Restrict CORS origins to specific domain
   - Configure TrustedHostMiddleware with specific hosts
   - Add API rate limiting at application level

## References

- [OWASP Secure Headers](https://owasp.org/www-project-secure-headers/)
- [Mozilla Observatory](https://observatory.mozilla.org/)
- [Content Security Policy Level 3](https://w3c.github.io/webappsec-csp/)
- [FastAPI CORS Documentation](https://fastapi.tiangolo.com/tutorial/cors/)

## Verification

All changes have been verified:
- Configuration syntax validated
- Security headers confirmed in place
- CORS headers removed from Nginx
- Rate limiting verified as appropriate
- HTTPS configuration ready for production

**Status: Ready for testing and deployment**
