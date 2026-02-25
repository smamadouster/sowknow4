#!/bin/bash
set -e

echo "🔧 Fixing SOWKNOW Upload Errors"
echo "================================"

# 1. Fix database enum type
echo -e "\n📊 Step 1: Fixing database enum..."
docker-compose exec -T postgres psql -U sowknow -d sowknow <<EOF
ALTER TYPE documentbucket ADD VALUE IF NOT EXISTS 'public';
ALTER TYPE documentbucket ADD VALUE IF NOT EXISTS 'confidential';
SELECT unnest(enum_range(NULL::documentbucket)) AS "Available Bucket Values";
EOF

# 2. Create upload directories
echo -e "\n📁 Step 2: Creating upload directories..."
docker-compose exec backend mkdir -p /app/uploads/public /app/uploads/confidential || true
docker-compose exec backend chmod 755 /app/uploads/public /app/uploads/confidential || true
echo "✅ Upload directories created"

# 3. Fix Redis URL (remove password)
echo -e "\n🔧 Step 3: Checking Redis configuration..."
if grep -q "REDIS_URL=redis://:" .env 2>/dev/null; then
    echo "⚠️  Found Redis password in .env - removing it"
    sed -i 's|REDIS_URL=redis://:[^@]*@|REDIS_URL=redis://|g' .env
    echo "✅ Redis URL fixed"
else
    echo "✅ Redis URL looks correct"
fi

# 4. Restart services
echo -e "\n♻️  Step 4: Restarting services..."
docker-compose restart backend celery-worker celery-beat telegram-bot

echo -e "\n⏳ Waiting 10 seconds for services to stabilize..."
sleep 10

# 5. Verify health
echo -e "\n🏥 Step 5: Health checks..."

echo "Backend health:"
docker-compose exec backend curl -sf http://localhost:8000/health && echo "✅ Backend healthy" || echo "❌ Backend unhealthy"

echo "Database connection:"
docker-compose exec backend python -c "from app.database import engine; engine.connect(); print('✅ Database connected')" 2>&1 | tail -1

echo "Redis connection:"
docker-compose exec backend python -c "import redis; r = redis.Redis(host='redis'); print('✅ Redis OK') if r.ping() else print('❌ Redis down')" 2>&1 | tail -1

echo "Celery worker:"
docker-compose logs --tail=5 celery-worker | grep -q "ready" && echo "✅ Celery ready" || echo "⚠️  Celery still starting"

echo -e "\n================================"
echo "Fix script complete!"
echo ""
echo "Next: Test upload with Telegram bot"
