#!/bin/bash
# Automated SSL Certificate Setup with Monitoring for SOWKNOW
# This script sets up Let's Encrypt certificates with auto-renewal monitoring

set -e

# Configuration from environment or defaults
DOMAIN="${DOMAIN:-sowknow.gollamtech.com}"
EMAIL="${EMAIL:-admin@gollamtech.com}"
STAGING="${STAGING:-false}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================="
echo "SOWKNOW SSL Certificate Setup"
echo "Domain: $DOMAIN"
echo "Email: $EMAIL"
echo "Staging: $STAGING"
echo "========================================="

# Check if port 80 is available
if netstat -tuln 2>/dev/null | grep ':80 ' > /dev/null || ss -tuln 2>/dev/null | grep ':80 ' > /dev/null; then
    echo -e "${YELLOW}⚠️  Port 80 is already in use. Attempting to use existing setup...${NC}"
fi

# Create certbot directories
mkdir -p certbot-conf certbot-www

# Get certificate using certbot container
echo "Getting SSL certificate from Let's Encrypt..."

if [ "$STAGING" = "true" ]; then
    echo -e "${YELLOW}Using Let's Encrypt STAGING environment (for testing)${NC}"
    STAGING_FLAG="--staging"
else
    STAGING_FLAG=""
fi

docker run --rm \
    -p 80:80 \
    -v "$(pwd)/certbot-conf:/etc/letsencrypt" \
    -v "$(pwd)/certbot-www:/var/www/certbot" \
    certbot/certbot certonly --webroot \
    --email $EMAIL \
    --agree-tos \
    --no-eff-email \
    --webroot-path=/var/www/certbot \
    $STAGING_FLAG \
    -d $DOMAIN \
    -d www.$DOMAIN || {
    echo -e "${RED}❌ Failed to get certificate${NC}"
    echo "If you're testing, set STAGING=true to avoid rate limits"
    exit 1
}

# Create ssl directory
mkdir -p nginx/ssl

# Copy certificates to nginx directory
echo "Copying certificates to nginx ssl directory..."
docker run --rm \
    -v "$(pwd)/certbot-conf:/letsencrypt:ro" \
    -v "$(pwd)/nginx/ssl:/ssl" \
    alpine:latest \
    sh -c "
        if [ -f /letsencrypt/live/$DOMAIN/fullchain.pem ]; then
            cp /letsencrypt/live/$DOMAIN/fullchain.pem /ssl/
            cp /letsencrypt/live/$DOMAIN/privkey.pem /ssl/
            cp /letsencrypt/live/$DOMAIN/chain.pem /ssl/
            chmod 644 /ssl/fullchain.pem /ssl/privkey.pem /ssl/chain.pem
            echo 'Certificates copied successfully'
        else
            echo 'ERROR: Certificate files not found'
            exit 1
        fi
    "

# Create symlink for renewal
docker run --rm \
    -v "$(pwd)/certbot-conf:/etc/letsencrypt" \
    -v "$(pwd)/nginx/ssl:/ssl" \
    alpine:latest \
    sh -c "ln -sf /letsencrypt/live/$DOMAIN/fullchain.pem /ssl/fullchain.pem && \
            ln -sf /letsencrypt/live/$DOMAIN/privkey.pem /ssl/privkey.pem"

echo ""
echo -e "${GREEN}✅ SSL certificates installed successfully!${NC}"
echo "   Files in nginx/ssl/:"
ls -la nginx/ssl/

# Create SSL monitoring script
cat > scripts/check-ssl-expiry.sh << 'EOF'
#!/bin/bash
# Check SSL certificate expiry and send alerts

DOMAIN="${1:-sowknow.gollamtech.com}"
DAYS_WARNING=14

# Get expiry date from certificate
if [ -f "nginx/ssl/fullchain.pem" ]; then
    EXPIRY_DATE=$(openssl x509 -enddate -noout -in nginx/ssl/fullchain.pem | cut -d= -f2)
    EXPIRY_EPOCH=$(date -d "$EXPIRY_DATE" +%s)
    CURRENT_EPOCH=$(date +%s)
    DAYS_LEFT=$(( ($EXPIRY_EPOCH - $CURRENT_EPOCH) / 86400 ))

    echo "SSL Certificate for $DOMAIN expires in $DAYS_LEFT days ($EXPIRY_DATE)"

    if [ $DAYS_LEFT -lt $DAYS_WARNING ]; then
        echo "WARNING: Certificate expires soon! Renew immediately."
        exit 1
    else
        echo "Certificate is valid."
        exit 0
    fi
else
    echo "ERROR: Certificate file not found"
    exit 2
fi
EOF

chmod +x scripts/check-ssl-expiry.sh

# Create renewal cron job
cat > scripts/renew-ssl.sh << 'EOF'
#!/bin/bash
# Renew SSL certificate and reload nginx

echo "Checking SSL certificate renewal..."

docker run --rm \
    -v "$(pwd)/certbot-conf:/etc/letsencrypt" \
    -v "$(pwd)/certbot-www:/var/www/certbot" \
    certbot/certbot renew --webroot -w /var/www/certbot --quiet

# Reload nginx if certificate was renewed
if [ $? -eq 0 ]; then
    echo "Reloading nginx..."
    docker compose exec nginx nginx -s reload 2>/dev/null || echo "Nginx not running or reload failed"
fi
EOF

chmod +x scripts/renew-ssl.sh

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}SSL Setup Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Create an nginx SSL config: nginx/nginx-ssl.conf"
echo "2. Update docker-compose.yml to use the SSL config"
echo "3. Set up cron job for certificate renewal:"
echo "   0 0,12 * * * /path/to/sowknow4/scripts/renew-ssl.sh"
echo ""
echo "SSL monitoring commands:"
echo "  ./scripts/check-ssl-expiry.sh    # Check certificate expiry"
echo "  ./scripts/renew-ssl.sh           # Renew certificate"
