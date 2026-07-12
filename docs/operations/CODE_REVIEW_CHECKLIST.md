# SOWKNOW Code Review Checklist

Use this checklist for every non-trivial PR.

## Wiring

- [ ] Does this PR add code that is actually wired into the live app?
- [ ] If a new API router is added, is it imported and `include_router`-ed in `backend/app/main.py`?
- [ ] If a new Celery task is added, is its module in `celery_app.conf.include`?
- [ ] If a new task is scheduled in `beat_schedule`, is its module loaded by workers?
- [ ] If a new service/queue is added, is it in `docker-compose.production.yml`?
- [ ] If a new env var is added, is it documented in `.env.example` and read in code?
- [ ] If a new endpoint is added, is it covered by a cron script or frontend call?

## Metrics & observability

- [ ] If a new metric is added, is `/metrics` updated and scraped by Prometheus?
- [ ] If a new alert condition is added, is it registered and evaluated?
- [ ] Are host-level monitoring scripts (`scripts/monitor-*.sh`) updated if endpoints change?

## Security & permissions

- [ ] Are admin endpoints protected by role checks (backend + frontend)?
- [ ] Are feature flags actually read in code rather than only exported by deploy scripts?

## Cleanup

- [ ] Is any code left unreachable or duplicated?
- [ ] Are old `.env.example` entries for unused integrations removed?
