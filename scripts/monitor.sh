#!/bin/bash
# SOWKNOW Health Monitoring Script
# Checks container health and system resources

ALERT_EMAIL="admin@gollamtech.com"
VPS_IP="192.168.1.1"
MEMORY_THRESHOLD=80
DISK_THRESHOLD=80

echo "=== SOWKNOW Health Check - $(date) ==="

# Check all SOWKNOW containers
echo ""
echo "--- Container Status ---"
CONTAINERS=$(docker ps -a --filter "name=sowknow" --format "{{.Names}}\t{{.Status}}")
echo "$CONTAINERS"

# Check for unhealthy containers
UNHEALTHY=$(echo "$CONTAINERS" | grep -v "Up" | grep -v "Created")
if [ -n "$UNHEALTHY" ]; then
    echo "WARNING: Unhealthy containers found!"
    echo "$UNHEALTHY"
    
    # Try to restart unhealthy containers
    echo "Attempting to restart unhealthy containers..."
    docker ps -a --filter "name=sowknow" --format "{{.Names}}" | while read container; do
        STATUS=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null)
        if [ "$STATUS" != "running" ]; then
            echo "Restarting $container..."
            docker restart "$container" 2>/dev/null
        fi
    done
fi

# Check container memory usage
echo ""
echo "--- Memory Usage ---"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | grep sow

# Check total memory
TOTAL_MEM=$(free -m | awk '/^Mem:/{print $2}')
USED_MEM=$(free -m | awk '/^Mem:/{print $3}')
MEM_PERC=$((USED_MEM * 100 / TOTAL_MEM))

echo "Total Memory: ${TOTAL_MEM}MB"
echo "Used Memory: ${USED_MEM}MB (${MEM_PERC}%)"

if [ $MEM_PERC -gt $MEMORY_THRESHOLD ]; then
    echo "WARNING: Memory usage above ${MEMORY_THRESHOLD}%"
fi

# Check disk usage
echo ""
echo "--- Disk Usage ---"
df -h / | awk 'NR==2 {print "Disk: " $5 " used"}'

# Check API health
echo ""
echo "--- API Health ---"
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "API: Healthy"
else
    echo "API: Unreachable!"
fi

# Check frontend
echo ""
echo "--- Frontend Health ---"
if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    echo "Frontend: Healthy"
else
    echo "Frontend: Unreachable!"
fi

# Check nginx
echo ""
echo "--- Nginx Health ---"
if curl -sf http://localhost/health > /dev/null 2>&1; then
    echo "Nginx: Healthy"
else
    echo "Nginx: Unreachable!"
fi

# Check Redis
echo ""
echo "--- Redis Health ---"
if docker exec sowknow-redis redis-cli ping > /dev/null 2>&1; then
    echo "Redis: Healthy"
else
    echo "Redis: Unreachable!"
fi

# Check PostgreSQL
echo ""
echo "--- PostgreSQL Health ---"
if docker exec sowknow-postgres pg_isready -U sowknow > /dev/null 2>&1; then
    echo "PostgreSQL: Healthy"
else
    echo "PostgreSQL: Unreachable!"
fi

echo ""
echo "=== Health Check Complete ==="
