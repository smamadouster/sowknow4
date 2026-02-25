#!/bin/bash

echo "🔍 SOWKNOW Upload Failure Diagnostic"
echo "========================================"

# 1. Service Health
echo -e "\n📊 Service Status:"
docker-compose ps

# 2. Backend Logs
echo -e "\n📋 Recent Backend Errors:"
docker-compose logs --tail=50 backend | grep -i "error\|exception\|traceback" || echo "No errors found"

# 3. Storage Check
echo -e "\n💾 Storage Directories:"
docker-compose exec backend ls -la /app/uploads/ 2>/dev/null || echo "❌ Cannot access /app/uploads/"

# 4. Database Check
echo -e "\n🗄️ Database Connection:"
docker-compose exec backend python -c "from app.database import engine; conn = engine.connect(); print('✅ Database OK'); conn.close()" 2>/dev/null || echo "❌ Database connection failed"

# 5. Redis Check
echo -e "\n📮 Redis Connection:"
docker-compose exec backend python -c "import redis; r = redis.Redis(host='redis'); print('✅ Redis OK') if r.ping() else print('❌ Redis down')" 2>/dev/null || echo "❌ Redis connection failed"

# 6. Celery Worker Check
echo -e "\n⚙️ Celery Worker:"
docker-compose logs --tail=10 celery-worker | tail -n 5

# 7. Test Upload API
echo -e "\n🔬 Testing Upload API:"
echo "Test file content" > /tmp/test_upload.txt
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@/tmp/test_upload.txt" \
  -F "bucket=public" \
  -F "title=Diagnostic Test" \
  -w "\nHTTP Status: %{http_code}\n" \
  2>/dev/null || echo "❌ API unreachable"

# 8. Check migrations
echo -e "\n🔄 Database Migrations:"
docker-compose exec backend alembic current 2>/dev/null || echo "❌ Alembic not configured"

echo -e "\n========================================"
echo "Diagnostic complete. Check output above for issues."
