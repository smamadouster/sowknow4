# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-04-05

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->

## Key Learnings

- **Project:** sowknow4
- **Description:** [![Docker Compliance](https://github.com/anomalyco/sowknow4/actions/workflows/docker-compliance.yml/badge.svg)](https://github.com/anomalyco/sowknow4/actions/workflows/docker-compliance.yml)

## Do-Not-Repeat

<!-- Mistakes made and corrected. Each entry prevents the same mistake recurring. -->
<!-- Format: [YYYY-MM-DD] Description of what went wrong and what to do instead. -->
- [2026-04-07] NEVER use AsyncSessionLocal inside Celery tasks with asyncio.run(). The module-level async engine's connection pool binds to the first event loop; subsequent asyncio.run() calls create new loops → "Future attached to different loop". Use sync SessionLocal for DB ops, only asyncio.run() for HTTP calls.
- [2026-04-07] After adding columns to SQLAlchemy models, ALWAYS verify the migration was actually applied to the database (not just that alembic_version is correct). A partial migration can break every query touching that model.
- [2026-04-07] Production bind mount is /var/docker/sowknow4/backend, NOT /home/development/src/active/sowknow4/backend. Editing dev files doesn't change production. Must copy to /var/docker/sowknow4/ and clear __pycache__.
- [2026-04-10] Guardian HC plugin heals MUST go through RestartTracker. Without it, a probe bug (wrong import, missing auth) causes infinite restart loops — the container was healthy but kept being restarted every 2min because the probe kept failing.
- [2026-04-10] Guardian HC probes MUST classify their own errors. If a probe fails due to its own misconfiguration (wrong import path, missing credentials), it must return needs_healing=False — otherwise Guardian will restart a healthy container in a futile loop. Check stderr for ModuleNotFoundError/ImportError, stdout for NOAUTH.
- [2026-04-10] When writing `docker exec ... python3 -c` probes against the backend container: the bind mount is ./backend:/app, so code lives at /app/app/... → always use `from app.tasks.X import Y`, never `from tasks.X import Y`.
- [2026-04-10] Guardian v2 plugin heals log `success: True/False` but the dashboard/report counted healed via `h.get("healed")` (v1 field only). All plugin heal results must be checked as: `h.get("healed") or h.get("success") is True`.
- [2026-04-11] NEVER use `--pool=prefork` with `concurrency=1` for celery-heavy. fork() doubles the ~1.3GB model in memory → RSS hits cgroup limit → OOM kill. Use `--pool=solo`: single process, model loaded once, no fork overhead. solo pool ignores `--max-tasks-per-child` (use `--max-memory-per-child` as a safety valve instead).
- [2026-04-11] NUL bytes (0x00) in OCR'd text cause PostgreSQL "string literal cannot contain NUL characters" errors during chunk insert. Always strip with `text.replace('\x00', '')` before passing to the DB.

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->
- [2026-04-10] Guardian HC runbook system: YAML runbooks in monitoring/guardian-hc/runbooks/ matched by check_name. Runbooks take priority over generic plugin.heal(). RunbookEngine handles exec/restart/http_check/alert/wait steps with on_success/on_failure branching. Rationale: probe bugs caused infinite restart loops — runbooks add diagnosis before destructive actions.
- [2026-04-10] Guardian HC Dockerfile: added docker-ce-cli + postgresql-client. Without these, all docker exec and psql probes silently fail (exit 127). The Docker socket was mounted but no CLI was installed — this caused silent probe failures.
- [2026-04-10] Guardian HC guardian_hc/ and runbooks/ are now bind-mounted in docker-compose.yml (:ro). This means code changes in dev are reflected after docker restart, no image rebuild needed.
