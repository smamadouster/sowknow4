# Reverse Proxy Configuration - Deployment Checklist

## Quick Reference

### Important: Production Uses Caddy (Not Nginx)

**Production deployment uses Caddy reverse proxy**, not nginx. Caddy is already running on the VPS and handles:
- SSL/TLS termination (automatic Let's Encrypt)
- Reverse proxying to backend (port 8000) and frontend (port 3000)
- Port 80/443 binding

**Do NOT start the nginx container in production** - it will conflict with Caddy on ports 80/443.

### Configuration Files
- **Development/Testing (nginx):** `/root/development/src/active/sowknow4/nginx/nginx-http-only.conf`
- **Production (Caddy-managed):** Caddy routes configured via API
- **Backup nginx config:** `/root/development/src/active/sowknow4/nginx/nginx.conf` (not used in production)

### Which Configuration to Use?

| Environment | Reverse Proxy | Configuration |
|-------------|---------------|---------------|
| Development | nginx | `nginx-http-only.conf` |
| Production | Caddy | API-configured routes |

## Pre-Deployment Verification

### 1. Security Headers Check

All configurations must include these headers:

```bash
# Run this command to verify
curl -I http://localhost/ | grep -E "(X-Frame-Options|X-Content-Type|X-XSS|Referrer|Permissions)"
```

**Expected output:**
```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

### 2. CORS Check

**CRITICAL:** Nginx should NOT add CORS headers. Backend handles CORS.

```bash
# Test that Nginx doesn't add CORS
curl -H "Origin: https://example.com" -I http://localhost/api/v1/status | grep -i "access-control-allow"
```

**Expected:** No CORS headers from Nginx (backend may return them)

**If you see `Access-Control-Allow-Origin: *` from Nginx:** Configuration is incorrect!

### 3. Rate Limiting Check

```bash
# Test rate limiting
for i in {1..15}; do
  echo "Request $i:"
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost/api/v1/status
done
```

**Expected:** First 10-15 requests succeed (200), subsequent requests may be rate-limited (503)

### 4. Backend Configuration Check

**Verify production environment variables:**

```bash
# Check that these are set in backend/.env.production
grep -E "^(ALLOWED_ORIGINS|ALLOWED_HOSTS|APP_ENV)" /var/docker/sowknow4/backend/.env.production
```

**Expected:**
```
ALLOWED_ORIGINS=https://sowknow.gollamtech.com
ALLOWED_HOSTS=sowknow.gollamtech.com
APP_ENV=production
```

**WARNING:** If you see wildcards (`*`), the configuration is insecure for production!

### 5. SSL/TLS Check (Production with Caddy)

```bash
# Test SSL configuration (handled by Caddy)
openssl s_client -connect sowknow.gollamtech.com:443 -servername sowknow.gollamtech.com < /dev/null | grep -E "(Protocol|Cipher)"

# View Caddy configuration for SOWKNOW
docker exec ghostshell-caddy wget -qO- http://localhost:2019/config/apps/http/servers/srv2/routes 2>/dev/null | grep -A10 sowknow
```

**Expected:**
```
Protocol  : TLSv1.2 or TLSv1.3
Cipher    : ECDHE-ECDSA-AES128-GCM-SHA256 or similar strong cipher
```

**Note:** Caddy automatically handles SSL certificates. No manual renewal needed.

## Deployment Steps

### 1. Backup Current Configuration

```bash
cd /var/docker/sowknow4
cp nginx/nginx.conf nginx/nginx.conf.backup.$(date +%Y%m%d) 2>/dev/null || true
cp nginx/nginx-http-only.conf nginx/nginx-http-only.conf.backup.$(date +%Y%m%d) 2>/dev/null || true
```

### 2. Deploy Services (Production uses Caddy)

```bash
# For production (Caddy handles reverse proxy - do NOT start nginx)
docker-compose up -d backend frontend celery-worker celery-beat

# For development (nginx can be used)
docker-compose restart nginx
```

**Important:** In production, Caddy is already running on the VPS. Do not start the nginx container as it conflicts with Caddy on ports 80/443.

### 3. Verify Configuration

```bash
# Check Caddy routes are configured
docker exec ghostshell-caddy wget -qO- http://localhost:2019/config/apps/http/servers/srv2/routes 2>/dev/null | grep -A5 sowknow

# Check all sowknow containers are running
docker ps | grep sowknow

# Test the application
curl -I https://sowknow.gollamtech.com/
curl -I https://sowknow.gollamtech.com/api/health
```

### 4. Test Critical Endpoints (via Caddy/HTTPS)

```bash
# Health check
curl https://sowknow.gollamtech.com/health

# API status
curl https://sowknow.gollamtech.com/api/v1/status

# API docs (should return 200)
curl -I https://sowknow.gollamtech.com/api/docs
```

## Rollback Procedure

If issues occur after deployment:

```bash
# Restore backup
cp nginx/nginx.conf.backup.YYYYMMDD nginx/nginx.conf 2>/dev/null || true

# Restart services (production uses Caddy, not nginx)
docker-compose restart backend frontend

# Check logs
docker logs sowknow4-backend --tail 100
```

## Common Issues and Solutions

### Issue: CORS Errors in Browser

**Symptoms:** Browser console shows CORS errors

**Diagnosis:**
```bash
curl -H "Origin: https://sowknow.gollamtech.com" \
     -H "Access-Control-Request-Method: POST" \
     -X OPTIONS \
     http://localhost/api/v1/auth/login -v
```

**Solutions:**
1. Check backend `ALLOWED_ORIGINS` in `.env.production`
2. Verify backend is running and accessible
3. Check that Nginx is NOT adding CORS headers (should come from backend only)

### Issue: Rate Limiting Too Aggressive

**Symptoms:** Legitimate requests being blocked

**Solution:** Adjust rate limits in nginx configuration:

```nginx
# In nginx.conf or nginx-http-only.conf
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=20r/s;  # Increase from 10r/s
limit_req_zone $binary_remote_addr zone=general_limit:10m rate=60r/s;  # Increase from 30r/s
```

Then restart nginx.

### Issue: CSP Blocking Resources

**Symptoms:** Browser console shows CSP violations

**Diagnosis:** Check browser console for specific CSP violations

**Solution:** Adjust CSP policy in nginx configuration:

```nginx
# In location / block
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.example.com; ...";
```

**Warning:** Only add necessary origins. Avoid overly permissive policies.

### Issue: API Docs Not Loading

**Symptoms:** Swagger UI doesn't load or shows errors

**Diagnosis:**
```bash
curl -I http://localhost/api/docs
```

**Solution:** Ensure X-Frame-Options override is in place:

```nginx
location /api/docs {
    add_header X-Frame-Options "SAMEORIGIN" always;
}
```

## Monitoring

### Log Monitoring

```bash
# Follow Caddy logs in real-time (production reverse proxy)
docker logs -f ghostshell-caddy 2>&1 | grep -i sowknow

# Check for errors
docker logs ghostshell-caddy 2>&1 | grep -i "error\|sowknow"

# For development nginx (if used)
docker logs -f sowknow4-nginx 2>/dev/null || echo "nginx not running (production uses Caddy)"
```

### Health Monitoring

```bash
# Create a simple health check script for Caddy/SOWKNOW
cat > /tmp/sowknow-health.sh << 'EOF'
#!/bin/bash
curl -sf https://sowknow.gollamtech.com/health || exit 1
curl -sf https://sowknow.gollamtech.com/api/v1/status || exit 1
echo "SOWKNOW health check passed"
EOF

chmod +x /tmp/sowknow-health.sh

# Run every minute via cron
# * * * * * /tmp/sowknow-health.sh
```

## Security Reminders

### Before Going Live

1. [ ] SSL certificates are valid and not expired
2. [ ] `ALLOWED_ORIGINS` set to specific HTTPS URLs (no wildcards)
3. [ ] `ALLOWED_HOSTS` set to specific hostnames (no wildcards)
4. [ ] Rate limiting is appropriate for expected traffic
5. [ ] Security headers are present and correct
6. [ ] Backend `APP_ENV=production`
7. [ ] No test/debug endpoints exposed
8. [ ] API keys are secure and not in version control
9. [ ] Database and Redis passwords are strong
10. [ ] Firewall rules restrict access to necessary ports only

### After Going Live

1. [ ] Monitor error logs regularly
2. [ ] Set up alerts for 5xx errors
3. [ ] Monitor rate limiting effectiveness
4. [ ] Review security headers occasionally
5. [ ] Keep SSL certificates updated (Caddy auto-renews)
6. [ ] Regular security audits

## Contact

For issues or questions about the reverse proxy configuration, refer to:
- `SECURITY_CHANGES.md` - Detailed change documentation
- Project documentation in `/var/docker/sowknow4/`
- Caddy documentation: https://caddyserver.com/docs/
- Nginx documentation: https://nginx.org/en/docs/ (for development only)

## Version History

- **2026-02-20:** Production uses Caddy reverse proxy
  - Caddy handles SSL/TLS termination (not nginx)
  - Caddy routes configured via API
  - Nginx container disabled in production (port conflict prevention)
  - Documentation updated to reflect Caddy usage

- **2026-02-10:** Initial security hardening
  - Removed wildcard CORS from Nginx
  - Added security headers
  - Verified rate limiting
  - Prepared for production deployment
