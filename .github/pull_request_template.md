## Summary

<!-- What does this PR do? -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / cleanup
- [ ] Infrastructure / deployment
- [ ] Documentation

## Wiring checklist

- [ ] New API router is imported and `include_router`-ed in `backend/app/main.py`
- [ ] New Celery task module is added to `backend/app/celery_app.py` `conf.include`
- [ ] New beat-scheduled task is loaded by a worker queue
- [ ] New env vars are documented in `.env.example` and read somewhere in code
- [ ] New monitoring endpoint is reachable from `scripts/*.sh` if intended
- [ ] Feature flags are read in code, not only set in deploy scripts
- [ ] Manual test confirms the feature is reachable from a real request path

## Verification

- [ ] `PYTHONPATH=backend python scripts/wiring_check.py` passes
- [ ] Backend tests pass: `PYTHONPATH=backend pytest tests/unit/`
- [ ] Frontend builds: `cd frontend && npm run build`
- [ ] Docker compose config is valid: `docker-compose -f docker-compose.production.yml config`
