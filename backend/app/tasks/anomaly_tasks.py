"""
Celery tasks for anomaly detection and scheduled reports
"""

import logging
from datetime import UTC, datetime, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.anomaly_tasks.daily_anomaly_report")
def daily_anomaly_report() -> dict:
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
    import os

    from app.database import SessionLocal
    from app.services.cache_monitor import cache_monitor
    from app.services.monitoring import (
        SystemMonitor,
        get_cost_tracker,
        get_queue_monitor,
    )

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
        from app.models.processing import ProcessingQueue, TaskStatus  # noqa: F401

        db = SessionLocal()
        try:
            cutoff_time = report_time - timedelta(hours=24)

            # Query documents with status='processing' and updated_at > 24 hours ago
            # Use .value to ensure proper enum string comparison
            stuck_documents = (
                db.query(Document)
                .filter(
                    Document.status == DocumentStatus.PROCESSING.value,
                    Document.updated_at < cutoff_time,
                )
                .all()
            )

            for doc in stuck_documents:
                # Get additional processing info if available
                try:
                    processing_task = db.query(ProcessingQueue).filter(ProcessingQueue.document_id == doc.id).first()
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
                    "created_at": (doc.created_at.isoformat() if doc.created_at else None),
                    "updated_at": (doc.updated_at.isoformat() if doc.updated_at else None),
                    "stuck_duration_hours": round(duration_hours, 2),
                    "last_task_type": (
                        processing_task.task_type.value
                        if processing_task and hasattr(processing_task, "task_type")
                        else None
                    ),
                    "error_message": (
                        processing_task.error_message
                        if processing_task and hasattr(processing_task, "error_message")
                        else None
                    ),
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
            report["anomalies"].append(
                {
                    "type": "low_cache_hit_rate",
                    "severity": "warning",
                    "hit_rate": round(cache_hit_rate, 4),
                    "threshold": 0.3,
                    "message": f"Cache hit rate below 30%: {cache_hit_rate:.1%}",
                }
            )
            warning_count += 1

        report["cache_stats"] = cache_monitor.get_stats_summary(days=1)

    except Exception as e:
        logger.warning(f"Failed to get cache stats: {e}")

    # 3. Check queue depth
    try:
        queue_monitor = get_queue_monitor()
        queue_depth = queue_monitor.get_queue_depth()

        if queue_depth > 100:
            report["anomalies"].append(
                {
                    "type": "queue_congestion",
                    "severity": "warning",
                    "queue_depth": queue_depth,
                    "threshold": 100,
                    "message": f"Queue depth exceeds 100: {queue_depth} tasks pending",
                }
            )
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
            report["anomalies"].append(
                {
                    "type": "high_memory_usage",
                    "severity": "warning",
                    "percent": mem_stats["percent"],
                    "threshold": 80,
                    "message": f"Memory usage above 80%: {mem_stats['percent']}%",
                }
            )
            warning_count += 1

        disk_stats = system_monitor.get_disk_usage()
        if disk_stats.get("alert_high"):
            report["anomalies"].append(
                {
                    "type": "high_disk_usage",
                    "severity": "critical",
                    "percent": disk_stats.get("percent", 0),
                    "threshold": 85,
                    "message": f"Disk usage above 85%: {disk_stats.get('percent', 0)}%",
                }
            )
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
            report["anomalies"].append(
                {
                    "type": "budget_exceeded",
                    "severity": "critical",
                    "daily_cost_usd": round(daily_cost, 2),
                    "budget_usd": daily_budget,
                    "message": f"Daily API budget exceeded: ${daily_cost:.2f} > ${daily_budget}",
                }
            )
            critical_count += 1
        elif daily_cost > daily_budget * 0.8:
            report["anomalies"].append(
                {
                    "type": "budget_warning",
                    "severity": "warning",
                    "daily_cost_usd": round(daily_cost, 2),
                    "budget_usd": daily_budget,
                    "percent_used": round((daily_cost / daily_budget) * 100, 1),
                    "message": f"API cost at 80% of budget: ${daily_cost:.2f} / ${daily_budget}",
                }
            )
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

    # Send external alert ONLY for critical unresolved issues.
    # Warnings are included in the daily Guardian HC report at 7 AM.
    if critical_count > 0:
        try:
            import asyncio

            from app.services.alert_service import alert_service

            severity = "CRITICAL"
            summary_lines = [
                f"• CRITICAL: {critical_count}",
                f"• WARNING: {warning_count}",
                "",
            ]
            for anomaly in report["anomalies"][:5]:  # first 5
                summary_lines.append(
                    f"  [{anomaly.get('severity', '?')}] {anomaly.get('type', '?')}: {anomaly.get('message', '')[:80]}"
                )
            if len(report["anomalies"]) > 5:
                summary_lines.append(f"  … and {len(report['anomalies']) - 5} more")

            coro = alert_service.send_anomaly_alert(
                anomaly_type="Daily Anomaly Report",
                details="\n".join(summary_lines),
                severity=severity,
                metadata={
                    "critical": critical_count,
                    "warning": warning_count,
                    "total": len(report["anomalies"]),
                    "generated_at": report["generated_at"],
                },
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(coro)
                else:
                    loop.run_until_complete(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception as alert_err:
            logger.warning(f"daily_anomaly_report: alert dispatch failed: {alert_err}")

    return report


@shared_task(name="app.tasks.anomaly_tasks.system_health_check")
def system_health_check() -> dict:
    """
    Perform comprehensive system health checks.

    Returns:
        dict with system health status
    """
    import redis

    from app.services.cache_monitor import cache_monitor
    from app.services.monitoring import (
        SystemMonitor,
        get_alert_manager,
        get_queue_monitor,
    )

    health_status = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy",
        "checks": {},
    }

    try:
        # Check database connection
        try:
            from app.database import SessionLocal

            db = SessionLocal()
            try:
                db.execute("SELECT 1")
                health_status["checks"]["database"] = {
                    "status": "healthy",
                    "message": "Database accessible",
                }
            finally:
                db.close()
        except Exception as e:
            health_status["checks"]["database"] = {
                "status": "unhealthy",
                "message": str(e),
            }
            health_status["overall_status"] = "degraded"

        # Check Redis connection
        try:
            from app.core.redis_url import safe_redis_url

            r = redis.from_url(safe_redis_url())
            r.ping()
            health_status["checks"]["redis"] = {
                "status": "healthy",
                "message": "Redis accessible",
            }
        except Exception as e:
            health_status["checks"]["redis"] = {
                "status": "unhealthy",
                "message": str(e),
            }
            health_status["overall_status"] = "degraded"

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
            health_status["checks"]["queue_depth"] = {
                "status": "error",
                "message": str(e),
            }

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
            health_status["checks"]["system_resources"] = {
                "status": "error",
                "message": str(e),
            }

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
def check_api_costs(daily_budget_threshold: float = 5.0) -> dict:
    """
    Check daily API costs and alert if approaching threshold.

    Args:
        daily_budget_threshold: Daily budget threshold in USD

    Returns:
        dict with cost tracking data
    """
    import os

    from app.services.monitoring import get_alert_manager, get_cost_tracker

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
        "percent_used": (round((daily_cost / daily_budget) * 100, 1) if daily_budget > 0 else 0),
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


@shared_task(name="app.tasks.anomaly_tasks.recover_stuck_documents")
def recover_stuck_documents(max_processing_minutes: int = 15) -> dict:
    """
    Find and recover documents stuck in 'processing' state for too long.
    This handles cases where a Celery worker crashed or was killed.

    THROTTLED: Recovers at most MAX_RECOVERY_PER_RUN documents per invocation
    to prevent queue flooding that starves new uploads.

    Args:
        max_processing_minutes: Maximum time a document should be in processing state

    Returns:
        dict with recovery results
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.processing import ProcessingQueue, TaskStatus
    from app.tasks.document_tasks import process_document

    MAX_RECOVERY_PER_RUN = 10  # Never flood the queue

    db = SessionLocal()
    recovered = []
    failed = []

    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=max_processing_minutes)

        # Find documents stuck in processing state — LIMIT to prevent queue bombs
        stuck_documents = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.PROCESSING,
                Document.updated_at < cutoff_time,
            )
            .order_by(Document.updated_at.asc())  # Oldest first
            .limit(MAX_RECOVERY_PER_RUN)
            .all()
        )

        for doc in stuck_documents:
            try:
                # Get processing task info
                processing_task = db.query(ProcessingQueue).filter(ProcessingQueue.document_id == doc.id).first()

                # Check if this is a real stuck document or just slow processing
                stuck_duration = (datetime.now(UTC) - doc.updated_at).total_seconds() / 60

                logger.warning(
                    f"Document {doc.id} ({doc.filename}) stuck in processing for {stuck_duration:.1f} minutes"
                )

                # Track how many times we've already recovered this document.
                # Always build a NEW dict to guarantee SQLAlchemy detects the mutation
                # (same-object assignment can be silently skipped by the ORM).
                existing_meta = doc.document_metadata or {}
                recovery_count = existing_meta.get("recovery_count", 0) + 1

                # After 3 recovery attempts, mark as permanently failed
                MAX_RECOVERY_ATTEMPTS = 3
                if recovery_count > MAX_RECOVERY_ATTEMPTS:
                    # Attempt to retrieve the actual Celery task error
                    actual_error = None
                    celery_task_id = existing_meta.get("celery_task_id")
                    if celery_task_id:
                        try:
                            from celery.result import AsyncResult
                            task_result = AsyncResult(celery_task_id)
                            if task_result.traceback:
                                actual_error = str(task_result.traceback)[:1000]
                        except Exception:
                            pass

                    doc.status = DocumentStatus.ERROR
                    doc.document_metadata = {
                        **existing_meta,
                        "recovery_count": recovery_count,
                        "recovered_from_stuck": True,
                        "stuck_duration_minutes": stuck_duration,
                        "recovered_at": datetime.now(UTC).isoformat(),
                        "processing_error": (
                            f"Permanently failed: stuck in processing after {recovery_count} recovery attempts"
                        ),
                        "actual_error": actual_error or "No traceback available (task result expired or not found)",
                    }

                    if processing_task:
                        processing_task.status = TaskStatus.FAILED
                        processing_task.error_message = f"Exhausted {MAX_RECOVERY_ATTEMPTS} recovery attempts"

                    db.commit()
                    logger.error(f"Document {doc.id} permanently failed after {recovery_count} recovery attempts")
                    failed.append(
                        {
                            "document_id": str(doc.id),
                            "error": f"Exhausted {MAX_RECOVERY_ATTEMPTS} recovery attempts",
                        }
                    )
                    continue

                # Reset document to pending state for reprocessing (use new dict copy)
                doc.status = DocumentStatus.PENDING
                doc.document_metadata = {
                    **existing_meta,
                    "recovery_count": recovery_count,
                    "recovered_from_stuck": True,
                    "stuck_duration_minutes": stuck_duration,
                    "recovered_at": datetime.now(UTC).isoformat(),
                }

                if processing_task:
                    processing_task.status = TaskStatus.PENDING
                    processing_task.error_message = f"Recovered from stuck state after {stuck_duration:.1f} minutes"
                    processing_task.retry_count = 0  # Reset retry count

                db.commit()

                # Re-queue the document for processing
                process_document.delay(str(doc.id))

                recovered.append(
                    {
                        "document_id": str(doc.id),
                        "filename": doc.filename,
                        "stuck_duration_minutes": round(stuck_duration, 1),
                        "recovery_attempt": recovery_count,
                    }
                )

                logger.info(
                    f"Re-queued stuck document {doc.id} for processing (attempt {recovery_count}/{MAX_RECOVERY_ATTEMPTS})"
                )

            except Exception as e:
                logger.error(f"Failed to recover document {doc.id}: {e}")
                failed.append({"document_id": str(doc.id), "error": str(e)})

        return {
            "timestamp": datetime.now().isoformat(),
            "max_processing_minutes": max_processing_minutes,
            "stuck_count": len(stuck_documents),
            "recovered": recovered,
            "failed": failed,
        }

    finally:
        db.close()


@shared_task(name="app.tasks.anomaly_tasks.recover_pending_documents")
def recover_pending_documents(pending_threshold_minutes: int = 5) -> dict:
    """
    Find and recover documents stuck in PENDING status.

    These are documents that were created but never successfully queued for
    processing or whose processing never completed. This can happen if:
    - The upload endpoint crashed after commit but before _queue_document_for_processing
    - Redis was unavailable when process_document.delay() was called
    - The database commit failed after the Celery task was queued
    - The Celery task was queued but never picked up by a worker
    - The Celery task failed silently

    Recovery strategy:
      - Find documents with status=PENDING (with or without celery_task_id)
      - Check if the celery_task_id exists in Redis results
      - If no task exists or task failed, re-queue the document
      - After 3 failed recovery attempts, mark as ERROR

    Args:
        pending_threshold_minutes: Minutes before a PENDING doc is considered stuck.
                                  Default 5 minutes (allows for normal processing delay).

    Returns:
        dict with recovery results
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.tasks.document_tasks import process_document

    db = SessionLocal()
    recovered = []
    failed = []
    already_queued = []

    try:
        MAX_RECOVERY_PER_RUN = 10  # Never flood the queue

        cutoff = datetime.now(UTC) - timedelta(minutes=pending_threshold_minutes)

        pending_docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.PENDING,
                Document.created_at < cutoff,
            )
            .order_by(Document.created_at.asc())  # Oldest first
            .limit(MAX_RECOVERY_PER_RUN)
            .all()
        )

        logger.info(f"Found {len(pending_docs)} PENDING documents to check")

        for doc in pending_docs:
            try:
                existing_meta = doc.document_metadata or {}
                recovery_count = existing_meta.get("pending_recovery_count", 0) + 1

                # After 3 recovery attempts, mark as permanently failed
                MAX_RECOVERY_ATTEMPTS = 3
                if recovery_count > MAX_RECOVERY_ATTEMPTS:
                    # Attempt to retrieve the actual Celery task error
                    actual_error = None
                    celery_task_id = existing_meta.get("celery_task_id")
                    if celery_task_id:
                        try:
                            from celery.result import AsyncResult
                            task_result = AsyncResult(celery_task_id)
                            if task_result.traceback:
                                actual_error = str(task_result.traceback)[:1000]
                        except Exception:
                            pass

                    error_msg = f"Failed to queue after {MAX_RECOVERY_ATTEMPTS} attempts"
                    doc.status = DocumentStatus.ERROR
                    doc.document_metadata = {
                        **existing_meta,
                        "pending_recovery_count": recovery_count,
                        "recovery_error": error_msg,
                        "processing_error": error_msg,
                        "actual_error": actual_error or "No traceback available",
                    }
                    db.commit()
                    logger.error(
                        f"Document {doc.id} permanently marked as ERROR after {MAX_RECOVERY_ATTEMPTS} failed recovery attempts"
                    )
                    failed.append(
                        {
                            "document_id": str(doc.id),
                            "filename": doc.filename,
                            "error": f"Exhausted {MAX_RECOVERY_ATTEMPTS} recovery attempts",
                        }
                    )
                    continue

                logger.warning(f"Attempting to recover PENDING document {doc.id} ({doc.filename})")

                celery_task_id = existing_meta.get("celery_task_id")
                needs_requeue = True

                if celery_task_id:
                    try:
                        from app.celery_app import celery_app

                        inspect = celery_app.control.inspect(timeout=5.0)
                        active_tasks = inspect.active() or {}
                        reserved_tasks = inspect.reserved() or {}
                        for worker_tasks in active_tasks.values():
                            for t in worker_tasks:
                                if t.get("id") == celery_task_id:
                                    needs_requeue = False
                                    logger.info(
                                        f"Document {doc.id} has task {celery_task_id} currently active, skipping"
                                    )
                                    break
                        if needs_requeue:
                            for worker_tasks in reserved_tasks.values():
                                for t in worker_tasks:
                                    if t.get("id") == celery_task_id:
                                        needs_requeue = False
                                        logger.info(f"Document {doc.id} has task {celery_task_id} reserved, skipping")
                                        break
                    except Exception as inspect_err:
                        logger.warning(f"Could not check task status for {celery_task_id}: {inspect_err}")

                if not needs_requeue:
                    already_queued.append(
                        {
                            "document_id": str(doc.id),
                            "filename": doc.filename,
                            "celery_task_id": celery_task_id,
                        }
                    )
                    continue

                # Try to queue the document for processing
                task = process_document.delay(str(doc.id))

                # Success - update status to PROCESSING
                doc.status = DocumentStatus.PROCESSING
                doc.document_metadata = {
                    **existing_meta,
                    "pending_recovery_count": recovery_count,
                    "celery_task_id": task.id,
                    "recovered_from_pending": True,
                    "recovered_at": datetime.now(UTC).isoformat(),
                }
                db.commit()

                recovered.append(
                    {
                        "document_id": str(doc.id),
                        "filename": doc.filename,
                        "celery_task_id": task.id,
                        "recovery_attempt": recovery_count,
                    }
                )
                logger.info(f"Successfully recovered PENDING document {doc.id}, queued with task {task.id}")

            except Exception as e:
                logger.error(f"Failed to recover PENDING document {doc.id}: {e}")
                # Increment recovery count even on failure
                try:
                    existing_meta = doc.document_metadata or {}
                    doc.document_metadata = {
                        **existing_meta,
                        "pending_recovery_count": existing_meta.get("pending_recovery_count", 0) + 1,
                        "last_recovery_error": str(e),
                    }
                    db.commit()
                except Exception:
                    pass
                failed.append({"document_id": str(doc.id), "error": str(e)})

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "pending_threshold_minutes": pending_threshold_minutes,
            "total_found": len(pending_docs),
            "recovered": recovered,
            "already_queued": already_queued,
            "failed": failed,
        }

    except Exception as e:
        logger.error(f"Error in recover_pending_documents: {e}")
        db.rollback()
        raise

    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# on_failure callback
# ─────────────────────────────────────────────────────────────────────────────


def on_daily_anomaly_report_failure(self, exc, task_id, args, kwargs, einfo) -> None:
    """on_failure callback for the daily_anomaly_report task."""
    logger.error(f"on_daily_anomaly_report_failure: task_id={task_id} exc={exc!r}")
    try:
        from app.tasks.base import base_task_failure_handler

        base_task_failure_handler(
            task_self=self,
            exception=exc,
            task_id=task_id,
            args=args,
            kwargs=kwargs,
            traceback=einfo,
            is_critical=False,
        )
    except Exception as cb_err:
        logger.error(f"on_daily_anomaly_report_failure handler error: {cb_err}")


@shared_task(name="app.tasks.anomaly_tasks.fail_stuck_processing_documents")
def fail_stuck_processing_documents(max_processing_minutes: int = 30) -> dict:
    """
    Find and fail documents stuck in PROCESSING status.

    This is a safety net for documents whose Celery task was:
    - Lost in the broker
    - Worker killed mid-processing
    - Redis failure that lost the task

    Args:
        max_processing_minutes: Minutes before a PROCESSING doc is considered stuck.

    Returns:
        dict with failure results
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus

    db = SessionLocal()
    failed = []
    ok = []

    try:
        from app.celery_app import celery_app

        cutoff = datetime.now(UTC) - timedelta(minutes=max_processing_minutes)

        stuck_docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.PROCESSING,
                Document.updated_at < cutoff,
            )
            .all()
        )

        logger.info(f"Checking {len(stuck_docs)} PROCESSING documents for stuck status")

        inspect = celery_app.control.inspect(timeout=10.0)
        active_tasks = inspect.active() or {}
        reserved_tasks = inspect.reserved() or {}

        active_ids = set()
        for _worker, tasks in active_tasks.items():
            for t in tasks:
                active_ids.add(t.get("id"))
        for _worker, tasks in reserved_tasks.items():
            for t in tasks:
                active_ids.add(t.get("id"))

        for doc in stuck_docs:
            celery_task_id = doc.document_metadata.get("celery_task_id") if doc.document_metadata else None

            if celery_task_id and celery_task_id in active_ids:
                ok.append({"document_id": str(doc.id), "task_id": celery_task_id})
                continue

            # Try to capture actual Celery error
            actual_error = None
            if celery_task_id:
                try:
                    from celery.result import AsyncResult
                    task_result = AsyncResult(celery_task_id)
                    if task_result.traceback:
                        actual_error = str(task_result.traceback)[:1000]
                except Exception:
                    pass

            existing_meta = doc.document_metadata or {}
            error_msg = f"Processing stuck > {max_processing_minutes} minutes, task {'not found in broker' if celery_task_id else 'never queued'}"
            doc.status = DocumentStatus.ERROR
            doc.document_metadata = {
                **existing_meta,
                "failure_reason": error_msg,
                "processing_error": error_msg,
                "failed_at": datetime.now(UTC).isoformat(),
                "actual_error": actual_error or "No traceback available",
            }
            failed.append(
                {
                    "document_id": str(doc.id),
                    "filename": doc.filename,
                    "celery_task_id": celery_task_id,
                }
            )
            logger.warning(f"Auto-failed stuck document {doc.id}: {doc.filename}")

        if failed:
            db.commit()

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "max_processing_minutes": max_processing_minutes,
            "total_checked": len(stuck_docs),
            "ok": len(ok),
            "failed": len(failed),
            "failed_documents": failed,
        }

    except Exception as e:
        logger.error(f"Error in fail_stuck_processing_documents: {e}")
        db.rollback()
        raise
    finally:
        db.close()
