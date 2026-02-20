#!/bin/bash
# SOWKNOW SSL and Nginx Fix Script
# Fixes Error 525 by resolving nginx config and SSL certificate issues

set -e

DOMAIN="sowknow.gollamtech.com"
EMAIL="admin@gollamtech.com"
PROJECT_DIR="/var/docker/sowknow4"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  SOWKNOW SSL & Nginx Fix Script${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# Step 1: Check if running from correct directory
cd "$PROJECT_DIR" 2>/dev/null || {
    echo -e "${RED}ERROR: Cannot access $PROJECT_DIR${NC}"
    echo "Please run this script from /var/docker/sowknow4 or set PROJECT_DIR"
    exit 1
}

# Step 2: Update nginx configuration
echo -e "${YELLOW}[1/5] Updating nginx configuration...${NC}"

# Ensure nginx config uses correct container names
if grep -q "server backend:8000" nginx/nginx.conf; then
    echo "Updating container names in nginx.conf..."
    sed -i 's/server backend:8000/server sowknow4-backend:8000/g' nginx/nginx.conf
    sed -i 's/server frontend:3000/server sowknow4-frontend:3000/g' nginx/nginx.conf
fi

# Step 3: Stop nginx temporarily to free port 80/443
echo -e "${YELLOW}[2/5] Stopping sowknow-nginx container...${NC}"
docker stop sowknow-nginx 2>/dev/null || true
docker rm sowknow-nginx 2>/dev/null || true

# Also stop any other containers using port 80
echo "Checking for other containers using port 80..."
CONTAINERS_ON_80=$(docker ps --format "{{.Names}}" --filter "publish=80" 2>/dev/null | grep -v "sowknow-nginx" || true)
if [ -n "$CONTAINERS_ON_80" ]; then
    echo -e "${YELLOW}Stopping containers using port 80: $CONTAINERS_ON_80${NC}"
    echo "$CONTAINERS_ON_80" | xargs -r docker stop
fi

# Step 4: Request SSL Certificate
echo -e "${YELLOW}[3/5] Requesting SSL certificate from Let's Encrypt...${NC}"

# Create certbot directories
mkdir -p certbot-www
mkdir -p nginx/ssl

# Check if certificate already exists
if docker run --rm -v certbot-conf:/etc/letsencrypt alpine:latest \
    test -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" 2>/dev/null; then
    echo -e "${GREEN}Certificate already exists. Skipping request.${NC}"
else
    echo "Requesting new certificate for $DOMAIN..."
    echo "Make sure DNS A record for $DOMAIN points to this server"

    # Get certificate using standalone mode
    docker run --rm -it \
        -p 80:80 \
        -v certbot-www:/var/www/certbot \
        -v certbot-conf:/etc/letsencrypt \
        certbot/certbot certonly --standalone \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email \
        -d "$DOMAIN" || {
        echo -e "${RED}ERROR: Failed to obtain certificate${NC}"
        echo "Check:"
        echo "  1. DNS A record for $DOMAIN points to this server's IP"
        echo "  2. Port 80 is accessible from the internet"
        echo "  3. No firewall blocking port 80"
        exit 1
    }

    # Copy certificates
    echo "Copying certificates to nginx/ssl/..."
    docker run --rm \
        -v certbot-conf:/letsencrypt:ro \
        -v "$PROJECT_DIR/nginx/ssl:/ssl" \
        alpine:latest sh -c "
            cp /letsencrypt/live/$DOMAIN/fullchain.pem /ssl/ &&
            cp /letsencrypt/live/$DOMAIN/privkey.pem /ssl/ &&
            chmod 644 /ssl/fullchain.pem /ssl/privkey.pem &&
            ls -la /ssl/
        "
fi

# Step 5: Restart any stopped containers
echo -e "${YELLOW}[4/5] Restarting stopped containers...${NC}"
if [ -n "$CONTAINERS_ON_80" ]; then
    echo "$CONTAINERS_ON_80" | xargs -r docker start
fi

# Step 6: Start sowknow-nginx with correct network
echo -e "${YELLOW}[5/5] Starting sowknow-nginx...${NC}"

# Get the correct network name
NETWORK_NAME=$(docker network ls --filter "name=sowknow" --format "{{.Name}}" | head -1)
if [ -z "$NETWORK_NAME" ]; then
    echo -e "${RED}ERROR: No sowknow network found${NC}"
    exit 1
fi

echo "Using network: $NETWORK_NAME"

# Start nginx container
docker run -d \
    --name sowknow-nginx \
    --restart unless-stopped \
    --network "$NETWORK_NAME" \
    -p 80:80 \
    -p 443:443 \
    -v "$PROJECT_DIR/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$PROJECT_DIR/nginx/ssl:/etc/nginx/ssl:ro" \
    -v certbot-www:/var/www/certbot:ro \
    -v certbot-conf:/etc/letsencrypt:ro \
    nginx:alpine

# Wait for nginx to start
sleep 3

# Check if nginx is running
if docker ps | grep -q "sowknow-nginx"; then
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  SUCCESS! Nginx is now running${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo "Checking nginx status..."
    docker ps --filter "name=sowknow-nginx" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "Your site should now be accessible at:"
    echo "  https://$DOMAIN"
    echo ""
    echo "If you still see Error 525, wait 2-3 minutes for Cloudflare to update."
else
    echo -e "${RED}ERROR: Nginx failed to start${NC}"
    echo "Checking logs:"
    docker logs sowknow-nginx 2>&1 | tail -20
    exit 1
fi

# Setup auto-renewal cron job
echo ""
echo "Setting up automatic certificate renewal..."
CRON_JOB="0 3 * * * /var/docker/sowknow4/scripts/ssl-auto-renewal.sh renew >> /var/log/sowknow-ssl-cron.log 2>&1"
(crontab -l 2>/dev/null | grep -v "ssl-auto-renewal") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
echo -e "${GREEN}Cron job added for daily renewal at 3:00 AM${NC}"

echo ""
echo -e "${GREEN}Fix complete!${NC}"
echo ""
echo "Useful commands:"
echo "  View nginx logs:     docker logs -f sowknow-nginx"
echo "  Check certificate:   ./scripts/ssl-auto-renewal.sh status"
echo "  Manual renewal:      ./scripts/ssl-auto-renewal.sh renew"
echo "  Diagnose issues:     ./scripts/ssl-auto-renewal.sh diagnose"
