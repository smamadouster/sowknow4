"""
Celery tasks for anomaly detection and scheduled reports
"""
from celery import shared_task
from app.celery_app import celery_app
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.anomaly_tasks.daily_anomaly_report")
def daily_anomaly_report():
    """
    Generate comprehensive daily anomaly report.
    Scheduled to run at 09:00 AM daily via Celery Beat.

    Per PRD requirements, this report includes:
    - Documents stuck in processing > 24h
    - Cache effectiveness metrics
    - System health status
    - Queue depth analysis
    - Cost tracking summary
    - API error rates

    Returns:
        dict with comprehensive anomaly report data
    """
    from app.database import SessionLocal
    from app.services.monitoring import (
        get_cost_tracker,
        get_queue_monitor,
        SystemMonitor,
    )
    from app.services.cache_monitor import cache_monitor
    import os

    report_time = datetime.now()
    report = {
        "report_type": "daily_anomaly_report",
        "generated_at": report_time.isoformat(),
        "summary": {
            "total_anomalies": 0,
            "severity_counts": {"critical": 0, "warning": 0, "info": 0},
        },
        "anomalies": [],
    }

    # Initialize counters
    critical_count = 0
    warning_count = 0

    # 1. Check for stuck documents (if database models exist)
    # Per PRD: Documents stuck in 'processing' status for more than 24 hours
    try:
        from app.models.document import Document, DocumentStatus
        from app.models.processing import ProcessingQueue, TaskStatus

        db = SessionLocal()
        try:
            cutoff_time = report_time - timedelta(hours=24)

            # Query documents with status='processing' and updated_at > 24 hours ago
            # Use .value to ensure proper enum string comparison
            stuck_documents = db.query(Document).filter(
                Document.status == DocumentStatus.PROCESSING.value,
                Document.updated_at < cutoff_time
            ).all()

            for doc in stuck_documents:
                # Get additional processing info if available
                try:
                    processing_task = db.query(ProcessingQueue).filter(
                        ProcessingQueue.document_id == doc.id
                    ).first()
                except Exception:
                    processing_task = None

                # Calculate duration based on when document was last updated
                duration_hours = (report_time - doc.updated_at).total_seconds() / 3600

                anomaly = {
                    "type": "stuck_document",
                    "severity": "critical",
                    "document_id": str(doc.id),
                    "filename": doc.filename,
                    "bucket": doc.bucket.value if hasattr(doc, "bucket") else "unknown",
                    "status": doc.status.value,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None,
                    "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                    "stuck_duration_hours": round(duration_hours, 2),
                    "last_task_type": processing_task.task_type.value if processing_task and hasattr(processing_task, 'task_type') else None,
                    "error_message": processing_task.error_message if processing_task and hasattr(processing_task, 'error_message') else None
                }
                report["anomalies"].append(anomaly)
                critical_count += 1

            if stuck_documents:
                logger.warning(f"Found {len(stuck_documents)} documents stuck in processing for >24 hours")

        finally:
            db.close()

    except ImportError as e:
        logger.debug(f"Document models not available, skipping stuck document check: {e}")
    except Exception as e:
        logger.error(f"Error checking stuck documents: {e}")

    # 2. Check cache effectiveness
    try:
        cache_hit_rate = cache_monitor.get_hit_rate(days=1)
        if cache_hit_rate < 0.3 and cache_hit_rate > 0:  # Only if there's traffic
            report["anomalies"].append({
                "type": "low_cache_hit_rate",
                "severity": "warning",
                "hit_rate": round(cache_hit_rate, 4),
                "threshold": 0.3,
                "message": f"Cache hit rate below 30%: {cache_hit_rate:.1%}",
            })
            warning_count += 1

        report["cache_stats"] = cache_monitor.get_stats_summary(days=1)

    except Exception as e:
        logger.warning(f"Failed to get cache stats: {e}")

    # 3. Check queue depth
    try:
        queue_monitor = get_queue_monitor()
        queue_depth = queue_monitor.get_queue_depth()

        if queue_depth > 100:
            report["anomalies"].append({
                "type": "queue_congestion",
                "severity": "warning",
                "queue_depth": queue_depth,
                "threshold": 100,
                "message": f"Queue depth exceeds 100: {queue_depth} tasks pending",
            })
            warning_count += 1

        report["queue_stats"] = {
            "depth": queue_depth,
            "all_depths": queue_monitor.get_all_queue_depths(),
        }

    except Exception as e:
        logger.warning(f"Failed to get queue stats: {e}")

    # 4. Check system resources
    try:
        system_monitor = SystemMonitor()
        mem_stats = system_monitor.get_memory_usage()

        if mem_stats["percent"] > 80:
            report["anomalies"].append({
                "type": "high_memory_usage",
                "severity": "warning",
                "percent": mem_stats["percent"],
                "threshold": 80,
                "message": f"Memory usage above 80%: {mem_stats['percent']}%",
            })
            warning_count += 1

        disk_stats = system_monitor.get_disk_usage()
        if disk_stats.get("alert_high"):
            report["anomalies"].append({
                "type": "high_disk_usage",
                "severity": "critical",
                "percent": disk_stats.get("percent", 0),
                "threshold": 85,
                "message": f"Disk usage above 85%: {disk_stats.get('percent', 0)}%",
            })
            critical_count += 1

        report["system_stats"] = {
            "memory": mem_stats,
            "disk": disk_stats,
        }

    except Exception as e:
        logger.warning(f"Failed to get system stats: {e}")

    # 5. Check API costs
    try:
        cost_tracker = get_cost_tracker()
        daily_cost = cost_tracker.get_daily_cost()
        daily_budget = float(os.getenv("GEMINI_DAILY_BUDGET_USD", "5.0"))

        if daily_cost > daily_budget:
            report["anomalies"].append({
                "type": "budget_exceeded",
                "severity": "critical",
                "daily_cost_usd": round(daily_cost, 2),
                "budget_usd": daily_budget,
                "message": f"Daily API budget exceeded: ${daily_cost:.2f} > ${daily_budget}",
            })
            critical_count += 1
        elif daily_cost > daily_budget * 0.8:
            report["anomalies"].append({
                "type": "budget_warning",
                "severity": "warning",
                "daily_cost_usd": round(daily_cost, 2),
                "budget_usd": daily_budget,
                "percent_used": round((daily_cost / daily_budget) * 100, 1),
                "message": f"API cost at 80% of budget: ${daily_cost:.2f} / ${daily_budget}",
            })
            warning_count += 1

        report["cost_stats"] = cost_tracker.get_stats(days=7)

    except Exception as e:
        logger.warning(f"Failed to get cost stats: {e}")

    # 6. Summary
    report["summary"]["total_anomalies"] = len(report["anomalies"])
    report["summary"]["severity_counts"] = {
        "critical": critical_count,
        "warning": warning_count,
        "info": len(report["anomalies"]) - critical_count - warning_count,
    }

    # Log the report
    if critical_count > 0:
        logger.error(f"Daily anomaly report: {critical_count} CRITICAL, {warning_count} WARNING issues found")
    elif warning_count > 0:
        logger.warning(f"Daily anomaly report: {warning_count} WARNING issues found")
    else:
        logger.info("Daily anomaly report: No anomalies detected")

    return report


@shared_task(name="app.tasks.anomaly_tasks.system_health_check")
def system_health_check():
    """
    Perform comprehensive system health checks.

    Returns:
        dict with system health status
    """
    from app.services.monitoring import (
        get_queue_monitor,
        get_alert_manager,
        SystemMonitor,
    )
    from app.services.cache_monitor import cache_monitor
    import redis
    import os
    import httpx

    health_status = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy",
        "checks": {}
    }

    try:
        # Check database connection
        try:
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                db.execute("SELECT 1")
                health_status["checks"]["database"] = {"status": "healthy", "message": "Database accessible"}
            finally:
                db.close()
        except Exception as e:
            health_status["checks"]["database"] = {"status": "unhealthy", "message": str(e)}
            health_status["overall_status"] = "degraded"

        # Check Redis connection
        try:
            r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            r.ping()
            health_status["checks"]["redis"] = {"status": "healthy", "message": "Redis accessible"}
        except Exception as e:
            health_status["checks"]["redis"] = {"status": "unhealthy", "message": str(e)}
            health_status["overall_status"] = "degraded"

        # Check Ollama connection
        try:
            ollama_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
            response = httpx.get(f"{ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                health_status["checks"]["ollama"] = {"status": "healthy", "message": "Ollama accessible"}
            else:
                health_status["checks"]["ollama"] = {"status": "degraded", "message": f"Status {response.status_code}"}
        except Exception as e:
            health_status["checks"]["ollama"] = {"status": "unhealthy", "message": str(e)}

        # Check queue depth
        try:
            queue_monitor = get_queue_monitor()
            queue_depth = queue_monitor.get_queue_depth()
            worker_status = queue_monitor.get_worker_status()

            if queue_depth > 100:
                health_status["checks"]["queue_depth"] = {
                    "status": "warning",
                    "message": f"{queue_depth} pending tasks",
                    "depth": queue_depth,
                    "worker_status": worker_status,
                }
                health_status["overall_status"] = "degraded"
            else:
                health_status["checks"]["queue_depth"] = {
                    "status": "healthy",
                    "depth": queue_depth,
                    "worker_status": worker_status,
                }
        except Exception as e:
            health_status["checks"]["queue_depth"] = {"status": "error", "message": str(e)}

        # Check system resources
        try:
            system_monitor = SystemMonitor()
            mem_stats = system_monitor.get_memory_usage()
            disk_stats = system_monitor.get_disk_usage()

            health_status["checks"]["memory"] = {
                "status": "healthy" if not mem_stats.get("alert_high") else "warning",
                "percent": mem_stats["percent"],
                "available_mb": mem_stats["available_mb"],
            }

            health_status["checks"]["disk"] = {
                "status": "healthy" if not disk_stats.get("alert_high") else "warning",
                "percent": disk_stats.get("percent", 0),
                "free_gb": disk_stats.get("free_gb", 0),
            }

            if mem_stats.get("alert_high") or disk_stats.get("alert_high"):
                health_status["overall_status"] = "degraded"

        except Exception as e:
            health_status["checks"]["system_resources"] = {"status": "error", "message": str(e)}

        # Check cache effectiveness
        try:
            cache_hit_rate = cache_monitor.get_hit_rate(days=1)
            health_status["checks"]["cache"] = {
                "status": "healthy",
                "hit_rate_24h": round(cache_hit_rate, 4),
                "tokens_saved_24h": cache_monitor.get_total_tokens_saved(days=1),
            }
        except Exception as e:
            health_status["checks"]["cache"] = {"status": "error", "message": str(e)}

        # Check active alerts
        try:
            alert_manager = get_alert_manager()
            active_alerts = alert_manager.get_active_alerts()
            health_status["checks"]["alerts"] = {
                "status": "healthy" if len(active_alerts) == 0 else "warning",
                "active_count": len(active_alerts),
                "active_alerts": active_alerts,
            }

            if active_alerts:
                health_status["overall_status"] = "degraded"

        except Exception as e:
            health_status["checks"]["alerts"] = {"status": "error", "message": str(e)}

        logger.info(f"System health check completed: {health_status['overall_status']}")
        return health_status

    except Exception as e:
        logger.error(f"Error during health check: {str(e)}")
        health_status["overall_status"] = "error"
        health_status["error"] = str(e)
        return health_status


@shared_task(name="app.tasks.anomaly_tasks.check_api_costs")
def check_api_costs(daily_budget_threshold: float = 5.0):
    """
    Check daily API costs and alert if approaching threshold.

    Args:
        daily_budget_threshold: Daily budget threshold in USD

    Returns:
        dict with cost tracking data
    """
    from app.services.monitoring import get_cost_tracker, get_alert_manager
    import os

    cost_tracker = get_cost_tracker()
    alert_manager = get_alert_manager()

    # Get actual budget from environment
    daily_budget = float(os.getenv("GEMINI_DAILY_BUDGET_USD", str(daily_budget_threshold)))
    daily_cost = cost_tracker.get_daily_cost()

    result = {
        "timestamp": datetime.now().isoformat(),
        "daily_cost_usd": round(daily_cost, 4),
        "daily_budget_usd": daily_budget,
        "remaining_budget": round(max(0, daily_budget - daily_cost), 4),
        "percent_used": round((daily_cost / daily_budget) * 100, 1) if daily_budget > 0 else 0,
        "breakdown": cost_tracker.get_daily_cost_breakdown(),
        "over_budget": daily_cost > daily_budget,
    }

    # Check alerts
    if daily_cost > daily_budget:
        alert_manager.check_alert("cost_over_budget", daily_cost)
        logger.warning(f"API cost over budget: ${daily_cost:.2f} > ${daily_budget:.2f}")
    elif daily_cost > daily_budget * 0.8:
        logger.warning(f"API cost at 80% of budget: ${daily_cost:.2f} / ${daily_budget:.2f}")

    return result
