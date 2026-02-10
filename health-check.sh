#!/bin/bash

echo "=== SOWKNOW4 HEALTH CHECK ==="
echo ""

# Check Docker containers
echo "1. 🐳 DOCKER CONTAINERS:"
docker compose -f docker-compose.prebuilt.yml ps
echo ""

# Check backend health
echo "2. 🩺 BACKEND HEALTH:"
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ Backend is healthy"
    curl -s http://localhost:8000/health | python3 -m json.tool
else
    echo "❌ Backend is not responding"
fi
echo ""

# Check frontend
echo "3. 🎨 FRONTEND STATUS:"
if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200\|30"; then
    echo "✅ Frontend is responding"
else
    echo "⚠️  Frontend may have issues (check logs)"
fi
echo ""

# Check database
echo "4. 🗄️  DATABASE STATUS:"
if docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "SELECT 1" > /dev/null 2>&1; then
    echo "✅ Database is connected"
    docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "SELECT COUNT(*) as users FROM sowknow.users;"
else
    echo "❌ Database connection failed"
fi
echo ""

# Check Redis
echo "5. 🧠 REDIS STATUS:"
if docker exec sowknow4-redis redis-cli ping | grep -q "PONG"; then
    echo "✅ Redis is connected"
else
    echo "❌ Redis connection failed"
fi
echo ""

echo "=== SYSTEM READY ==="
echo "Access points:"
echo "• Frontend: http://localhost:3000"
echo "• Backend:  http://localhost:8000"
echo "• API Docs: http://localhost:8000/api/docs"
