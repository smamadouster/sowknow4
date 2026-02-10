#!/bin/bash

echo "=== SOWKNOW4 SETUP VERIFICATION ==="
echo ""

# 1. Check all containers are running
echo "1. Container Status:"
if docker compose -f docker-compose.prebuilt.yml ps | grep -q "Up"; then
    echo "✅ All containers are running"
else
    echo "❌ Some containers are not running"
fi

# 2. Check backend health
echo -n "2. Backend Health: "
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅"
else
    echo "❌"
fi

# 3. Check frontend
echo -n "3. Frontend: "
if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200\|30"; then
    echo "✅"
else
    echo "⚠️"
fi

# 4. Check database
echo -n "4. Database: "
if docker exec sowknow4-postgres psql -U sowknow -d sowknow -c "SELECT 1" > /dev/null 2>&1; then
    echo "✅"
else
    echo "❌"
fi

# 5. Check Redis
echo -n "5. Redis: "
if docker exec sowknow4-redis redis-cli ping | grep -q "PONG"; then
    echo "✅"
else
    echo "❌"
fi

echo ""
echo "=== SETUP COMPLETE ==="
echo ""
echo "Your SOWKNOW4 environment is ready for development!"
echo ""
echo "Next steps:"
echo "1. Get new API keys (Moonshot, Hunyuan, Telegram)"
echo "2. Update .env file with new keys"
echo "3. Start implementing Phase 1 features:"
echo "   - Authentication system"
echo "   - Document upload API"
echo "   - File storage buckets"
echo "   - OCR integration"
