#!/bin/bash
# SOWKNOW Production Deployment Script
# Domain: sowknow.gollamtech.com

set -e

DOMAIN="sowknow.gollamtech.com"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EMAIL="admin@gollamtech.com"  # Change to your email

echo "========================================="
echo "SOWKNOW Production Deployment"
echo "Domain: $DOMAIN"
echo "========================================="

cd "$PROJECT_DIR"

# Step 1: Generate secrets if not exists
echo "[1/7] Checking secrets..."

if [ ! -f .secrets ]; then
    echo "Generating new secrets..."
    cat > .secrets <<EOF
# Generated on $(date)
POSTGRES_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)
EOF
    echo "Secrets generated in .secrets file"
fi

source .secrets

# Step 2: Create SSL certificates
echo "[2/7] Setting up SSL certificates..."

# Create directories
mkdir -p nginx/ssl
mkdir -p certbot-www

# Get initial certificate
docker run --rm -it \
  -v certbot-www:/var/www/certbot \
  -v certbot-conf:/etc/letsencrypt \
  -p 80:80 \
  certbot/certbot certonly --webroot \
  --webroot-path=/var/www/certbot \
  --email $EMAIL \
  --agree-tos \
  --no-eff-email \
  -d $DOMAIN

# Copy certificates to nginx ssl directory
docker run --rm \
  -v certbot-conf:/letsencrypt:ro \
  -v "$PROJECT_DIR/nginx/ssl:/ssl" \
  alpine:latest \
  sh -c "cp /letsencrypt/live/$DOMAIN/fullchain.pem /ssl/ && \
         cp /letsencrypt/live/$DOMAIN/privkey.pem /ssl/ && \
         chmod 644 /ssl/fullchain.pem /ssl/privkey.pem"

echo "SSL certificates installed"

# Step 3: Update backend environment
echo "[3/7] Configuring backend environment..."

cat > backend/.env.production <<EOF
# SOWKNOW Backend Production Environment
# Generated on $(date)

APP_NAME=SOWKNOW
APP_ENV=production
DEBUG=false
SECRET_KEY=$SECRET_KEY

DOMAIN=$DOMAIN
FRONTEND_URL=https://$DOMAIN
BACKEND_URL=https://$DOMAIN/api
API_DOCS_URL=https://$DOMAIN/api/docs

DATABASE_URL=postgresql://sowknow:$POSTGRES_PASSWORD@postgres:5432/sowknow?schema=sowknow
POSTGRES_USER=sowknow
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=sowknow

REDIS_URL=redis://:$REDIS_PASSWORD@redis:6379/0

GEMINI_API_KEY=$GEMINI_API_KEY
GEMINI_MODEL=gemini-2.0-flash-exp
GEMINI_CACHE_ENABLED=true

JWT_SECRET_KEY=$JWT_SECRET_KEY
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

MAX_UPLOAD_SIZE=104857600
UPLOAD_PATH=/app/uploads

CELERY_BROKER_URL=redis://:$REDIS_PASSWORD@redis:6379/1
CELERY_RESULT_BACKEND=redis://:$REDIS_PASSWORD@redis:6379/1

CORS_ORIGINS=https://$DOMAIN
CORS_ALLOW_CREDENTIALS=true

LOG_LEVEL=INFO
EOF

# Step 4: Update frontend environment
echo "[4/7] Configuring frontend environment..."

cat > frontend/.env.production <<EOF
NEXT_PUBLIC_APP_NAME=SOWKNOW
NEXT_PUBLIC_API_URL=https://$DOMAIN/api
NEXT_PUBLIC_APP_URL=https://$DOMAIN
NEXT_PUBLIC_ENV=production
NEXT_PUBLIC_DEFAULT_LANGUAGE=en
NEXT_PUBLIC_SUPPORTED_LANGUAGES=en,fr
NEXT_PUBLIC_ENABLE_KNOWLEDGE_GRAPH=true
NEXT_PUBLIC_ENABLE_SMART_COLLECTIONS=true
NEXT_PUBLIC_ENABLE_SMART_FOLDERS=true
NEXT_PUBLIC_ENABLE_MULTI_AGENT=true
EOF

# Step 5: Run database migrations
echo "[5/7] Running database migrations..."

docker-compose -f docker-compose.production.yml run --rm backend \
  alembic upgrade head

# Step 6: Build and start services
echo "[6/7] Building and starting services..."

docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml build
docker-compose -f docker-compose.production.yml up -d

# Wait for services to be healthy
echo "Waiting for services to start..."
sleep 10

# Step 7: Health check
echo "[7/7] Running health checks..."

if curl -sf https://$DOMAIN/health > /dev/null; then
    echo "✅ Backend is healthy"
else
    echo "⚠️  Backend health check failed"
fi

if curl -sf https://$DOMAIN/ > /dev/null; then
    echo "✅ Frontend is accessible"
else
    echo "⚠️  Frontend health check failed"
fi

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo "Application URL: https://$DOMAIN"
echo "API Docs: https://$DOMAIN/api/docs"
echo ""
echo "To view logs:"
echo "  docker-compose -f docker-compose.production.yml logs -f"
echo ""
echo "To restart services:"
echo "  docker-compose -f docker-compose.production.yml restart"
echo ""
