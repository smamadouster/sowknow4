#!/bin/bash
# Initial SSL Certificate Setup for SOWKNOW
# Run this once before deploying

DOMAIN="sowknow.gollamtech.com"
EMAIL="admin@gollamtech.com"  # Change this!

echo "========================================="
echo "SOWKNOW SSL Certificate Setup"
echo "Domain: $DOMAIN"
echo "Email: $EMAIL"
echo "========================================="

# Check if standalone server is running on port 80
if netstat -tuln | grep ':80 ' > /dev/null; then
    echo "⚠️  Port 80 is already in use. Please stop any web server first."
    echo "   You can temporarily stop nginx with: sudo systemctl stop nginx"
    exit 1
fi

# Get certificate using standalone mode
echo "Getting SSL certificate from Let's Encrypt..."
docker run --rm -it \
  -p 80:80 \
  -v "$(pwd)/certbot-conf:/etc/letsencrypt" \
  certbot/certbot certonly --standalone \
  --email $EMAIL \
  --agree-tos \
  --no-eff-email \
  -d $DOMAIN

# Create ssl directory
mkdir -p nginx/ssl

# Copy certificates
echo "Copying certificates to nginx ssl directory..."
docker run --rm \
  -v "$(pwd)/certbot-conf:/letsencrypt:ro" \
  -v "$(pwd)/nginx/ssl:/ssl" \
  alpine:latest \
  sh -c "cp /letsencrypt/live/$DOMAIN/fullchain.pem /ssl/ && \
         cp /letsencrypt/live/$DOMAIN/privkey.pem /ssl/ && \
         chmod 644 /ssl/fullchain.pem /ssl/privkey.pem && \
         ls -la /ssl/"

echo ""
echo "✅ SSL certificates installed successfully!"
echo "   Files in nginx/ssl/:"
ls -la nginx/ssl/

echo ""
echo "Next steps:"
echo "1. Run: ./scripts/deploy-production.sh"
echo "2. Or start services: docker-compose -f docker-compose.production.yml up -d"
