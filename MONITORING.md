# SOWKNOW Monitoring & Observability Guide

## Overview

SOWKNOW includes comprehensive monitoring and alerting infrastructure for production operations. This guide covers all monitoring endpoints, metrics, and operational procedures.

## Health Check Endpoints

### Basic Health Check
```bash
curl http://localhost:8000/health
```

Returns minimal status for container health checks:
```json
{
  "status": "healthy",
  "timestamp": 1770827789.748,
  "environment": "development",
  "version": "1.0.0",
  "services": {
    "database": "connected",
    "redis": "connected",
    "api": "running",
    "authentication": "enabled"
  }
}
```

### Detailed Health Check
```bash
curl http://localhost:8000/api/v1/health/detailed | jq .
```

Returns comprehensive health with all monitoring metrics:
- Memory usage per service
- Queue depth status
- Cost tracking summary
- Cache hit rate
- Active alerts
- System resource warnings

## Monitoring Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/health/detailed` | Comprehensive health check |
| `GET /api/v1/monitoring/costs?days=7` | API cost statistics |
| `GET /api/v1/monitoring/queue` | Celery queue depth |
| `GET /api/v1/monitoring/system` | System resources (memory, CPU, disk) |
| `GET /api/v1/monitoring/alerts` | Current alert status |
| `GET /metrics` | Prometheus metrics export |

## Prometheus Metrics

The `/metrics` endpoint exports all metrics in Prometheus format:

### HTTP Metrics
- `sowknow_http_requests_total` - Total HTTP requests
- `sowknow_http_request_duration_seconds` - Request latency histogram

### Database Metrics
- `sowknow_database_connections` - Active connections
- `sowknow_database_query_duration_seconds` - Query latency

### Queue Metrics
- `sowknow_celery_queue_depth` - Tasks in queue
- `sowknow_celery_workers_active` - Active workers
- `sowknow_celery_tasks_total` - Total tasks processed
- `sowknow_celery_task_duration_seconds` - Task duration

### LLM Metrics
- `sowknow_llm_requests_total` - Total API requests
- `sowknow_llm_tokens_total` - Total tokens (input/output/cached)
- `sowknow_llm_request_duration_seconds` - API latency
- `sowknow_llm_cost_usd` - Total cost in USD

### Cache Metrics
- `sowknow_cache_hit_rate` - Cache hit rate (0-1)
- `sowknow_cache_hits_total` - Total cache hits
- `sowknow_cache_misses_total` - Total cache misses

## Daily Anomaly Report

A daily anomaly report is generated at 09:00 AM via Celery Beat. The report includes:

### Anomalies Detected
1. **Stuck Documents** - Documents in processing > 24 hours
2. **Low Cache Hit Rate** - Cache hit rate below 30%
3. **Queue Congestion** - Queue depth exceeds 100 tasks
4. **High Memory Usage** - Memory usage above 80%
5. **High Disk Usage** - Disk usage above 85%
6. **Budget Alerts** - Daily API cost exceeds budget

### View Anomaly Report
```python
from app.tasks.anomaly_tasks import daily_anomaly_report
result = daily_anomaly_report.delay()
print(result.get())
```

## Cost Tracking

### Configure Daily Budget
Set the daily budget via environment variable:
```bash
export GEMINI_DAILY_BUDGET_USD=5.00
```

### View Cost Statistics
```bash
curl http://localhost:8000/api/v1/monitoring/costs?days=7 | jq .
```

Response includes:
- `total_cost_usd` - Total cost for period
- `average_daily_cost` - Average daily cost
- `daily_costs` - Daily breakdown
- `service_breakdown` - Cost by service
- `today_cost` - Today's cost
- `budget_remaining` - Remaining budget
- `over_budget` - Budget exceeded flag

### Record API Costs
```python
from app.services.monitoring import get_cost_tracker

cost_tracker = get_cost_tracker()
cost = cost_tracker.record_api_call(
    service="gemini",
    operation="chat",
    model="gemini-2.0-flash-exp",
    input_tokens=1000,
    output_tokens=500,
    cached_tokens=0
)
```

## Alert Thresholds

Default alert thresholds (configurable in `setup_default_alerts()`):

| Metric | Threshold | Duration |
|--------|-----------|----------|
| Memory usage | > 80% | 5 minutes |
| Disk usage | > 85% | 5 minutes |
| Queue depth | > 100 tasks | 5 minutes |
| API cost | > daily budget | 1 minute |

## SSL Certificate Management

### Setup SSL Certificates
```bash
./scripts/setup-ssl-auto.sh
```

This will:
1. Obtain Let's Encrypt certificates
2. Copy certificates to nginx/ssl/
3. Create monitoring scripts

### Check Certificate Expiry
```bash
./scripts/scripts/check-ssl-expiry.sh
```

### Renew Certificates
```bash
./scripts/scripts/renew-ssl.sh
```

### Setup Auto-Renewal Cron
```bash
# Add to crontab: 0 0,12 * * * /path/to/sowknow4/scripts/renew-ssl.sh
```

## Log Management

### View Container Logs
```bash
docker compose logs -f backend
docker compose logs --tail=100 backend
```

### Rotate Logs
```bash
./scripts/rotate-logs.sh
```

### Setup Log Rotation Cron
```bash
# Add to crontab:
0 2 * * * /root/development/src/active/sowknow4/scripts/rotate-logs.sh
```

### Log Aggregation (Optional)
```bash
./scripts/setup-log-aggregation.sh
docker compose -f docker-compose.logging.yml up -d
```

## System Resource Monitoring

### Check Memory Usage
```bash
curl http://localhost:8000/api/v1/monitoring/system | jq '.monitoring.memory'
```

### Check Queue Depth
```bash
curl http://localhost:8000/api/v1/monitoring/queue | jq '.monitoring.queue'
```

### Check Active Alerts
```bash
curl http://localhost:8000/api/v1/monitoring/alerts | jq '.active_alerts'
```

## Troubleshooting

### Backend Running as Root
```bash
docker exec sowknow4-backend whoami
# Should return: appuser
```

### Health Check Failing
```bash
# Check service dependencies
docker compose ps

# View service logs
docker logs sowknow4-backend
docker logs sowknow4-postgres
```

### High Memory Usage
```bash
# Check container memory limits
docker inspect sowknow4-backend | jq '.[0].HostConfig.Memory'

# Check current usage
docker stats --no-stream sowknow4-backend
```

## Production Deployment Checklist

- [ ] All 8 containers have health checks
- [ ] All 8 containers have `restart: unless-stopped`
- [ ] Backend running as non-root user (appuser)
- [ ] SSL certificates configured
- [ ] Log rotation cron configured
- [ ] Daily budget set (GEMINI_DAILY_BUDGET_USD)
- [ ] Prometheus scraping configured
- [ ] Alert notifications configured
- [ ] Anomaly report time verified (09:00 AM)
