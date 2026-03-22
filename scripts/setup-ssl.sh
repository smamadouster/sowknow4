#!/bin/bash
# SOWKNOW4 SSL Setup Script
# Fixes broken Python deps, obtains SSL certs, configures nginx
#
# Usage: sudo bash scripts/setup-ssl.sh
# After running: change Cloudflare SSL/TLS mode to "Full" for gollamtech.com

set -euo pipefail

DOMAINS=(sowknow.gollamtech.com guardian.gollamtech.com aichavu.gollamtech.com)
EMAIL="${CERTBOT_EMAIL:-admin@gollamtech.com}"
WEBROOT="/var/www/certbot"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== SOWKNOW4 SSL Setup ==="

# --- Step 1: Fix broken Python packages ---
echo ""
echo "[1/5] Fixing broken Python packages..."

# Remove corrupt /usr/local copies that shadow system packages
rm -rf /usr/local/lib/python3.12/dist-packages/idna
rm -rf /usr/local/lib/python3.12/dist-packages/requests
rm -rf /usr/local/lib/python3.12/dist-packages/pip

# Reinstall system packages
apt-get update -qq
apt-get install --reinstall -y -qq python3-idna python3-pip python3-requests 2>/dev/null

# Verify fix
python3 -c "import idna; print(f'  idna {idna.__version__} OK')"
python3 -c "import requests; print(f'  requests {requests.__version__} OK')"

# --- Step 2: Install certbot ---
echo ""
echo "[2/5] Installing certbot..."

apt-get install -y -qq certbot python3-certbot-nginx 2>/dev/null
certbot --version
echo "  certbot OK"

# --- Step 3: Stop stale certbot container ---
echo ""
echo "[3/5] Cleaning up stale certbot container..."

if docker ps -a --format '{{.Names}}' | grep -q '^sowknow-certbot$'; then
    docker stop sowknow-certbot 2>/dev/null || true
    docker rm sowknow-certbot 2>/dev/null || true
    echo "  Removed stale sowknow-certbot container"
else
    echo "  No stale certbot container found"
fi

# --- Step 4: Deploy nginx configs ---
echo ""
echo "[4/5] Deploying nginx site configs..."

mkdir -p "$WEBROOT"

for domain in "${DOMAINS[@]}"; do
    src="$REPO_DIR/nginx/sites/$domain"
    dest="/etc/nginx/sites-available/$domain"
    if [ -f "$src" ]; then
        cp "$src" "$dest"
        ln -sf "$dest" "/etc/nginx/sites-enabled/$domain"
        echo "  Deployed $domain"
    else
        echo "  SKIP $domain (no config in repo)"
    fi
done

nginx -t
nginx -s reload
echo "  nginx reloaded"

# --- Step 5: Obtain SSL certificates ---
echo ""
echo "[5/5] Obtaining SSL certificates..."

for domain in "${DOMAINS[@]}"; do
    echo "  Requesting cert for $domain..."
    certbot certonly \
        --webroot \
        -w "$WEBROOT" \
        -d "$domain" \
        --email "$EMAIL" \
        --agree-tos \
        --non-interactive \
        --keep-until-expiring \
        2>&1 | tail -3
    echo ""
done

echo "=== SSL Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Run: sudo certbot --nginx (to auto-configure SSL in nginx)"
echo "  2. Verify: curl -sk https://sowknow.gollamtech.com"
echo "  3. Change Cloudflare SSL/TLS to 'Full' mode"
echo "  4. Test all domains in browser"
echo ""
echo "Auto-renewal is handled by certbot's systemd timer:"
echo "  systemctl status certbot.timer"
