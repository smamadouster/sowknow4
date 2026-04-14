# anatomy.md

> Auto-maintained by OpenWolf. Last scanned: 2026-04-14T18:33:44.712Z
> Files: 927 tracked | Anatomy hits: 0 | Misses: 0

## ../../../../../tmp/

- `crontab.new` — ============================================================================ (~918 tok)

## ../../../../../var/docker/sowknow4/

- `docker-compose.yml` — Docker Compose services (~5834 tok)

## ../../../../../var/docker/sowknow4/backend/app/api/

- `voice.py` — API: 2 endpoints (~1514 tok)

## ../../../../../var/docker/sowknow4/backend/app/services/

- `chat_service.py` — OllamaService: chat_completion, health_check, get_conversation_history, retrieve_relevant_chunks + 1 (~7069 tok)
- `llm_router.py` — RoutingReason: generate_completion, detect_context_sensitivity, select_provider, build_messages + 1 (~3456 tok)
- `whisper_service.py` — WhisperService: transcribe (~745 tok)

## ../../../../../var/docker/sowknow4/backend/app/tasks/

- `voice_tasks.py` — transcribe_voice_note (~546 tok)

## ../../../../../var/docker/sowknow4/backend/telegram_bot/

- `bot.py` — RedisSessionManager: connect, close, get_session, set_session + 9 more (~18712 tok)

## ../../../../../var/docker/sowknow4/frontend/hooks/

- `useVoiceRecorder.ts` — Exports RecordingState, useVoiceRecorder (~2428 tok)

## ../../../../../var/docker/sowknow4/monitoring/guardian-hc/

- `guardian-hc.sowknow4.yml` — Guardian HC v2.0 -- SOWKNOW4 Configuration (~1740 tok)

## ../../../../../var/docker/sowknow4/monitoring/guardian-hc/guardian_hc/plugins/

- `infrastructure.py` — InfrastructurePlugin — wraps all v1 checkers and healers in the v2 plugin interface. (~7514 tok)
- `probes.py` — ProbesPlugin — deep application probes for Guardian (Watcher role). (~8178 tok)

## ../../../../../var/docker/sowknow4/monitoring/guardian-hc/scripts/

- `watchdog.sh` — ############################################################################## (~2126 tok)

## ../../../../mamadou/.claude/

- `settings.json` (~396 tok)

## ../../../../mamadou/.claude/projects/-home-development-src-active-sowknow4/memory/

- `MEMORY.md` — SOWKNOW Project Memory Index (~1048 tok)
- `project_april_8_outage.md` (~474 tok)
- `project_dictation_fr_to_en_fix.md` — 2026-04-10 fix (original) (~608 tok)
- `project_guardian_nftables_heal_broken.md` — Root Cause #5 — Confirmed 2026-04-14 (~1107 tok)
- `reference_production_deployment.md` (~874 tok)

## ../ghostshell/

- `docker-compose.yml` — Docker Compose services (~6439 tok)

## ../ghostshell/backend/alembic/versions/

- `013_add_crm_core_tables.py` — Add CRM core tables: products, crm_users, contact_products, campaigns. (~1282 tok)

## ../ghostshell/backend/app/

- `main.py` — AWA GhostShell - Main Application Entry Point (~10741 tok)

## ../ghostshell/backend/app/api/routes/integration/

- `__init__.py` — Integration API router assembly. (~182 tok)
- `brevo_webhooks.py` — POST /brevo/webhooks — receive Brevo email engagement events. (~1744 tok)

## ../ghostshell/backend/app/core/

- `config.py` — AWA GhostShell - Application Configuration (~3390 tok)

## ../ghostshell/backend/app/models/

- `integration.py` — SQLAlchemy models for the CRM Integration API Layer. (~2989 tok)

## ../ghostshell/backend/app/services/brevo/

- `__init__.py` (~0 tok)
- `client.py` — Thin httpx wrapper around the Brevo Contacts API v3. (~948 tok)
- `sync_service.py` — NATS subscriber that syncs CRM events to Brevo contact lists. (~1625 tok)

## ../ghostshell/backend/app/services/search/

- `searxng.py` — SearXNGProvider: is_configured, search, health_check, close (~1060 tok)

## ../ghostshell/backend/tests/

- `test_brevo_client.py` — Unit tests for BrevoClient. (~1194 tok)
- `test_brevo_sync.py` — Unit tests for BrevoSyncService NATS handlers. (~1902 tok)
- `test_brevo_webhooks.py` — Tests for Brevo webhook receiver. (~1494 tok)
- `test_integration_api.py` — Integration API Layer tests. (~6516 tok)

## ../ghostshell/config/caddy/

- `Caddyfile` — AWA GhostShell - Caddy Reverse Proxy Configuration (~841 tok)

## ../ghostshell/docs/superpowers/plans/

- `2026-04-11-integration-api-remaining-tasks.md` — GhostShell Integration API — Remaining Tasks Implementation Plan (~12343 tok)

## ../ghostshell/docs/superpowers/specs/

- `2026-04-11-integration-api-remaining-tasks-design.md` — Design Spec: GhostShell Integration API — Remaining Tasks (~2039 tok)

## ../ghostshell/scripts/

- `sre-daily-maintenance.sh` — SRE Daily Health Report — Direct host execution (~2123 tok)

## ./

- `.gitattributes` — Git attributes (~183 tok)
- `.gitignore` — Git ignore rules (~279 tok)
- `.pre-commit-config.yaml` (~115 tok)
- `.secrets` — ⚠️  ROTATE ALL THESE VALUES IMMEDIATELY ⚠️ (~252 tok)
- `.secrets.baseline` (~8828 tok)
- `AGENT_LEARNINGS.md` — Agent Learnings (~242 tok)
- `AI-ERVICES-CONFIGURATION.md` — AI Services Configuration Guide (~2083 tok)
- `Caddyfile.production` — Caddyfile for SOWKNOW production deployment (~516 tok)
- `CHANGELOG.md` — Change log (~1067 tok)
- `CLAUDE.md` — OpenWolf (~861 tok)
- `DATABASE-PASSWORD-GUIDE.md` — Database Password Change Guide (~1106 tok)
- `deploy-agentic-search.sh` — SOWKNOW4 — Deploy Agentic Search Enhancement (~771 tok)
- `deploy-production.sh` — SOWKNOW4 Production Deployment Script (Simplified) (~3074 tok)
- `DEPLOYMENT-PRODUCTION.md` — Production Deployment Guide - SOWKNOW4 (~2495 tok)
- `DEPLOYMENT.md` — SOWKNOW Deployment Guide (~1951 tok)
- `docker-compose.dev.yml` — Docker Compose: 4 services (~1246 tok)
- `docker-compose.prebuilt.yml` — Docker Compose: 4 services (~466 tok)
- `docker-compose.production.yml` — SOWKNOW Production Docker Compose (~3121 tok)
- `docker-compose.simple.yml` — Docker Compose: 4 services (~729 tok)
- `docker-compose.yml` — Docker Compose services (~5852 tok)
- `embed_chunked_docs.py` — run, db_query, redis_cmd, queue_depth + 6 more (~2009 tok)
- `fix-iptables.sh` — Fix for Docker DOCKER-INTERNAL chain blocking inter-container traffic (~218 tok)
- `health-check.sh` (~402 tok)
- `HURDLES_TO_PRODUCTION.md` — Hurdles to Production (~335 tok)
- `Mastertask.md` — Master Task: SOWKNOW Project Tracker (~743 tok)
- `MONITORING.md` — SOWKNOW Monitoring & Observability Guide (~1579 tok)
- `pytest.ini` (~94 tok)
- `README.md` — Project documentation (~2855 tok)
- `setup-env.sh` (~621 tok)
- `setup.cfg` — Python package configuration (~199 tok)
- `setup.sh` (~344 tok)
- `skills-lock.json` (~66 tok)
- `soul.md` — SOWKNOW — Soul Document (~640 tok)
- `SOWKNOW_AUDIT_REPORT.txt` (~143322 tok)
- `SOWKNOW_AUDIT_v2_2026-03-30.txt` — Declares and (~10224 tok)
- `sowknow_audit_v2.py` — URL configuration (~18000 tok)
- `sowknow_audit.py` — URL configuration (~16069 tok)
- `SOWKNOW_ExecutionPlan_v1.2.md` — SOWKNOW Multi-Generational Legacy Knowledge System (~7063 tok)
- `SOWKNOW_PRD_v1.1.md` — SOWKNOW Multi-Generational Legacy Knowledge System (~5335 tok)
- `SOWKNOW_PRD_v1.2.md` — SOWKNOW Multi-Generational Legacy Knowledge System (~6952 tok)
- `sowknow_runbook.py` — run, docker_exec, redis_cli, db_query + 4 more (~8306 tok)
- `sowknow_static_audit.sh` — SOWKNOW Static Code & Security Audit (~3290 tok)
- `SOWKNOW_TechStack_v1.1.md` — SOWKNOW Multi-Generational Legacy Knowledge System (~5094 tok)
- `sowknow_verify.sh` — ═══════════════════════════════════════════════════════════════════════ (~2748 tok)
- `verify-setup.sh` (~383 tok)

## .agents/skills/frontend-design/

- `SKILL.md` — Design Thinking (~1069 tok)

## .claude/

- `settings.json` (~441 tok)
- `settings.local.json` — Declares f (~733 tok)

## .claude/commands/

- `pr.md` — Declares is (~192 tok)

## .claude/projects/-home-development-src-active-sowknow4/memory/

- `project_docker_nftables_bug.md` (~361 tok)

## .claude/rules/

- `openwolf.md` (~313 tok)

## .github/workflows/

- `ci.yml` — CI: CI — Unit & E2E Tests (~675 tok)
- `docker-compliance.yml` — CI: Docker Compliance (~389 tok)
- `performance-benchmarks.yml` — CI: Performance Benchmarks (~765 tok)

## .pytest_cache/

- `.gitignore` — Git ignore rules (~10 tok)
- `CACHEDIR.TAG` (~51 tok)
- `README.md` — Project documentation (~76 tok)

## .pytest_cache/v/cache/

- `lastfailed` (~90 tok)
- `nodeids` (~9219 tok)

## .ruff_cache/

- `.gitignore` — Git ignore rules (~10 tok)
- `CACHEDIR.TAG` (~12 tok)

## .ruff_cache/0.15.2/

- `1053625930134714482` (~26 tok)
- `15959205584629996120` (~17 tok)
- `16000826108601056672` (~24 tok)
- `16170028892354602767` (~22 tok)
- `18145130784854709930` (~40 tok)
- `2421671516051681224` (~30 tok)
- `2974958397542667223` (~23 tok)
- `5138760891748630329` (~41 tok)
- `6894748257439071565` (~156 tok)
- `7422028052029269237` (~30 tok)
- `7776710558467357369` (~28 tok)
- `845820066658391125` (~41 tok)
- `8811677720756972853` (~41 tok)
- `881394957738623718` (~31 tok)
- `9017554146358118796` (~48 tok)
- `9687411456623053194` (~141 tok)

## .ruff_cache/0.15.3/

- `13984748288437182641` (~62 tok)
- `4979677117012901152` (~23 tok)
- `8214761925694487808` (~234 tok)
- `9536525009889484707` (~112 tok)

## .superpowers/brainstorm/1833855-1776019685/content/

- `pain-points.html` (~706 tok)

## .superpowers/brainstorm/1837747-1776019768/content/

- `bookmarks-mobile-design.html` — Bookmarks Mobile Design (~3956 tok)
- `pain-points.html` (~704 tok)
- `waiting-1.html` (~38 tok)

## .worktrees/feat/embed-server/

- `docker-compose.yml` — Docker Compose services (~5757 tok)

## .worktrees/feat/embed-server/.wolf/

- `anatomy.md` — anatomy.md (~10160 tok)

## .worktrees/feat/embed-server/backend/

- `Dockerfile.embed` (~290 tok)

## .worktrees/feat/embed-server/backend/app/services/

- `embed_client.py` — EmbedClient: embedding_dim, can_embed, health_check, encode + 3 more (~1342 tok)
- `search_service.py` — SearchResult: semantic_search, keyword_search, tag_search (~12207 tok)
- `similarity_service.py` — SimilarityGroup: to_dict, find_similar_groups, find_similar_to_document (~3703 tok)

## .worktrees/feat/embed-server/backend/app/tasks/

- `article_tasks.py` — Celery tasks: record_success, record_failure, allow_request, generate_articles_for_document, generat (~3922 tok)
- `document_tasks.py` — Celery tasks: detect_text_language, process_document (~9939 tok)
- `embedding_tasks.py` — generate_embeddings_batch, recompute_embeddings_for_document, upgrade_embeddings_model (~3172 tok)
- `pipeline_tasks.py` — _EmbedContinue: update_stage (~5127 tok)

## .worktrees/feat/embed-server/backend/embed_server/

- `__init__.py` — Package marker for embed_server microservice (~1 tok)
- `main.py` — API: 3 endpoints (~544 tok)
- `requirements.txt` — Python dependencies (~25 tok)

## .worktrees/feat/embed-server/backend/tests/

- `test_embed_client.py` — set_embed_url, get_client, test_encode_calls_embed_endpoint, test_encode_empty_returns_empty (~1257 tok)
- `test_embed_server.py` — client, test_health_ok, test_embed_returns_vectors, test_embed_empty_texts (~647 tok)

## audit_reports/

- `OCR_SERVICE_INTEGRATION_AUDIT_2026-02-21.md` — OCR Service Integration Audit Report (~5210 tok)
- `SOWKNOW_AUDIT_v2_2026-03-30.md` — SOWKNOW — Deep-Tier Agentic Stack Audit Report v2.0 (~8278 tok)
- `SOWKNOW_DEEP_TIER_AUDIT_2026-03-29.md` — SOWKNOW -- Multi-Generational Legacy Knowledge System (~139677 tok)

## backend/

- `alembic.ini` — A generic, single database configuration. (~858 tok)
- `benchmark_results.json` (~535 tok)
- `celerybeat-schedule` (~4369 tok)
- `Dockerfile` — Docker container definition (~179 tok)
- `Dockerfile.dev` (~87 tok)
- `Dockerfile.minimal` (~281 tok)
- `Dockerfile.telegram` (~148 tok)
- `Dockerfile.worker` (~824 tok)
- `entrypoint.sh` (~50 tok)
- `pipeline_status_check.py` — Quick pipeline status check — run inside backend container. (~232 tok)
- `pyproject.toml` — Python project configuration (~1556 tok)
- `pytest.ini` (~302 tok)
- `requirements-minimal.txt` — SOWKNOW Backend Requirements - Minimal Working Version (~292 tok)
- `requirements-telegram.txt` (~26 tok)
- `requirements.txt` — Python dependencies (~386 tok)
- `run_security_tests.sh` — SOWKNOW Security Test Runner (~661 tok)
- `test_security_config.py` — Tests: production_security, development_configuration, nginx_configuration (~2318 tok)
- `validate_security.py` — parse_allowed_origins, parse_allowed_hosts, test_security_config, check_env_files (~2673 tok)
- `worker-entrypoint.sh` (~191 tok)

## backend/.mypy_cache/

- `.gitignore` — Git ignore rules (~10 tok)
- `CACHEDIR.TAG` (~51 tok)

## backend/.mypy_cache/3.11/

- `__future__.data.json` (~2578 tok)
- `__future__.meta.json` (~214 tok)
- `_ast.data.json` (~3524 tok)
- `_ast.meta.json` (~239 tok)
- `_asyncio.data.json` (~18118 tok)
- `_asyncio.meta.json` (~333 tok)
- `_bisect.data.json` (~23063 tok)
- `_bisect.meta.json` (~244 tok)
- `_blake2.data.json` (~5954 tok)
- `_blake2.meta.json` (~244 tok)
- `_bz2.data.json` (~3083 tok)
- `_bz2.meta.json` (~242 tok)
- `_codecs.data.json` (~17427 tok)
- `_codecs.meta.json` (~295 tok)
- `_collections_abc.data.json` (~9071 tok)
- `_collections_abc.meta.json` (~246 tok)
- `_compat_pickle.data.json` (~1530 tok)
- `_compat_pickle.meta.json` (~196 tok)
- `_compression.data.json` (~4747 tok)
- `_compression.meta.json` (~277 tok)
- `_contextvars.data.json` (~21533 tok)
- `_contextvars.meta.json` (~282 tok)
- `_csv.data.json` (~7849 tok)
- `_csv.meta.json` (~292 tok)
- `_ctypes.data.json` (~66116 tok)
- `_ctypes.meta.json` (~294 tok)
- `_decimal.data.json` (~3695 tok)
- `_decimal.meta.json` (~262 tok)
- `_frozen_importlib_external.data.json` (~20471 tok)
- `_frozen_importlib_external.meta.json` (~489 tok)
- `_frozen_importlib.data.json` — Declares _frozen_importlib (~13110 tok)
- `_frozen_importlib.meta.json` (~378 tok)
- `_hashlib.data.json` (~14708 tok)
- `_hashlib.meta.json` (~279 tok)
- `_heapq.data.json` (~4602 tok)
- `_heapq.meta.json` (~224 tok)
- `_io.data.json` (~36873 tok)
- `_io.meta.json` (~323 tok)
- `_locale.data.json` (~7705 tok)
- `_locale.meta.json` (~225 tok)
- `_lsprof.data.json` (~5194 tok)
- `_lsprof.meta.json` (~278 tok)
- `_operator.data.json` (~30794 tok)
- `_operator.meta.json` (~296 tok)
- `_pickle.data.json` (~12732 tok)
- `_pickle.meta.json` (~279 tok)
- `_queue.data.json` (~4083 tok)
- `_queue.meta.json` (~211 tok)
- `_random.data.json` (~2145 tok)
- `_random.meta.json` (~244 tok)
- `_sitebuiltins.data.json` (~2547 tok)
- `_sitebuiltins.meta.json` (~230 tok)
- `_socket.data.json` (~41926 tok)
- `_socket.meta.json` (~295 tok)
- `_sqlite3.data.json` (~28483 tok)
- `_sqlite3.meta.json` (~296 tok)
- `_ssl.data.json` (~28529 tok)
- `_ssl.meta.json` (~293 tok)
- `_stat.data.json` (~8386 tok)
- `_stat.meta.json` (~224 tok)
- `_struct.data.json` (~4555 tok)
- `_struct.meta.json` (~247 tok)
- `_thread.data.json` (~17537 tok)
- `_thread.meta.json` (~327 tok)
- `_warnings.data.json` (~5684 tok)
- `_warnings.meta.json` (~226 tok)
- `_weakref.data.json` (~6633 tok)
- `_weakref.meta.json` (~212 tok)
- `_weakrefset.data.json` (~19566 tok)
- `_weakrefset.meta.json` (~248 tok)
- `@plugins_snapshot.json` (~1 tok)
- `abc.data.json` (~8690 tok)
- `abc.meta.json` (~245 tok)
- `app.data.json` (~432 tok)
- `app.meta.json` (~142 tok)
- `argparse.data.json` (~68707 tok)
- `argparse.meta.json` (~294 tok)
- `array.data.json` (~28576 tok)
- `array.meta.json` (~277 tok)
- `ast.data.json` (~149688 tok)
- `ast.meta.json` (~309 tok)
- `atexit.data.json` (~2986 tok)
- `atexit.meta.json` (~214 tok)
- `base64.data.json` (~4940 tok)
- `base64.meta.json` (~224 tok)
- `bdb.data.json` (~17129 tok)
- `bdb.meta.json` (~293 tok)
- `binascii.data.json` (~3693 tok)
- `binascii.meta.json` (~261 tok)
- `bisect.data.json` (~4163 tok)
- `bisect.meta.json` (~225 tok)
- `builtins.meta.json` (~378 tok)
- `bz2.data.json` (~13425 tok)
- `bz2.meta.json` (~340 tok)
- `calendar.data.json` (~19173 tok)
- `calendar.meta.json` (~311 tok)
- `cmath.data.json` (~5548 tok)
- `cmath.meta.json` (~227 tok)
- `cmd.data.json` (~6706 tok)
- `cmd.meta.json` (~228 tok)
- `codecs.data.json` (~42228 tok)
- `codecs.meta.json` (~294 tok)
- `colorsys.data.json` (~2447 tok)
- `colorsys.meta.json` (~193 tok)
- `configparser.data.json` (~55480 tok)
- `configparser.meta.json` (~297 tok)
- `contextlib.data.json` (~45008 tok)
- `contextlib.meta.json` (~295 tok)
- `contextvars.data.json` (~746 tok)
- `contextvars.meta.json` (~213 tok)
- `copy.data.json` (~3036 tok)
- `copy.meta.json` (~239 tok)
- `copyreg.data.json` (~4096 tok)
- `copyreg.meta.json` (~263 tok)
- `cProfile.data.json` (~6154 tok)
- `cProfile.meta.json` (~280 tok)
- `csv.data.json` (~12818 tok)
- `csv.meta.json` (~293 tok)
- `dataclasses.data.json` (~25964 tok)
- `dataclasses.meta.json` (~297 tok)
- `datetime.data.json` (~49469 tok)
- `datetime.meta.json` (~260 tok)
- `decimal.data.json` (~56711 tok)
- `decimal.meta.json` (~313 tok)
- `difflib.data.json` (~23094 tok)
- `difflib.meta.json` (~275 tok)
- `dis.data.json` (~23655 tok)
- `dis.meta.json` (~293 tok)
- `doctest.data.json` (~24958 tok)
- `doctest.meta.json` (~332 tok)
- `enum.data.json` (~38890 tok)
- `enum.meta.json` (~277 tok)
- `errno.data.json` (~8050 tok)
- `errno.meta.json` (~243 tok)
- `faulthandler.data.json` (~2188 tok)
- `faulthandler.meta.json` (~228 tok)
- `fcntl.data.json` (~9291 tok)
- `fcntl.meta.json` (~243 tok)
- `fnmatch.data.json` (~2262 tok)
- `fnmatch.meta.json` (~244 tok)
- `fractions.data.json` (~35902 tok)
- `fractions.meta.json` (~313 tok)
- `functools.data.json` (~63230 tok)
- `functools.meta.json` (~280 tok)
- `gc.data.json` (~5275 tok)
- `gc.meta.json` (~228 tok)
- `genericpath.data.json` (~10067 tok)
- `genericpath.meta.json` (~280 tok)
- `getpass.data.json` (~1322 tok)
- `getpass.meta.json` (~241 tok)
- `gettext.data.json` (~18797 tok)
- `gettext.meta.json` (~308 tok)
- `glob.data.json` — Declares glob (~4621 tok)
- `glob.meta.json` (~261 tok)
- `google.data.json` (~437 tok)
- `google.meta.json` (~142 tok)
- `gzip.data.json` (~17475 tok)
- `gzip.meta.json` (~322 tok)
- `hashlib.data.json` (~3381 tok)
- `hashlib.meta.json` (~277 tok)
- `heapq.data.json` (~3279 tok)
- `heapq.meta.json` (~243 tok)
- `hmac.data.json` (~4503 tok)
- `hmac.meta.json` (~278 tok)
- `inspect.data.json` (~132420 tok)
- `inspect.meta.json` (~328 tok)
- `io.data.json` (~2805 tok)
- `io.meta.json` (~254 tok)
- `ipaddress.data.json` (~53875 tok)
- `ipaddress.meta.json` (~280 tok)
- `itertools.data.json` (~199911 tok)
- `itertools.meta.json` (~280 tok)
- `keyword.data.json` (~1169 tok)
- `keyword.meta.json` (~211 tok)
- `linecache.data.json` (~2807 tok)
- `linecache.meta.json` (~248 tok)
- `locale.data.json` (~7246 tok)
- `locale.meta.json` (~312 tok)
- `marshal.data.json` (~2085 tok)
- `marshal.meta.json` (~260 tok)
- `math.data.json` (~24747 tok)
- `math.meta.json` (~277 tok)
- `mimetypes.data.json` — Declares of (~5434 tok)
- `mimetypes.meta.json` (~245 tok)
- `mmap.data.json` (~11380 tok)
- `mmap.meta.json` (~276 tok)
- `netrc.data.json` (~2579 tok)
- `netrc.meta.json` (~243 tok)
- `numbers.data.json` (~31525 tok)
- `numbers.meta.json` (~193 tok)
- `opcode.data.json` (~2161 tok)
- `opcode.meta.json` (~225 tok)
- `operator.data.json` (~31087 tok)
- `operator.meta.json` (~262 tok)
- `pdb.data.json` (~29912 tok)
- `pdb.meta.json` (~374 tok)
- `pickle.data.json` (~14696 tok)
- `pickle.meta.json` (~264 tok)
- `pickletools.data.json` (~14028 tok)
- `pickletools.meta.json` (~265 tok)
- `pkgutil.data.json` — Declares pkgutil (~11412 tok)
- `pkgutil.meta.json` (~298 tok)
- `platform.data.json` (~13413 tok)
- `platform.meta.json` (~245 tok)
- `posixpath.data.json` (~37832 tok)
- `posixpath.meta.json` (~297 tok)
- `pprint.data.json` (~7385 tok)
- `pprint.meta.json` (~242 tok)
- `profile.data.json` (~6453 tok)
- `profile.meta.json` (~247 tok)
- `pstats.data.json` (~15713 tok)
- `pstats.meta.json` (~344 tok)
- `pty.data.json` (~2614 tok)
- `pty.meta.json` (~261 tok)
- `pydoc.data.json` — Declares of (~35171 tok)
- `pydoc.meta.json` (~294 tok)
- `queue.data.json` (~8627 tok)
- `queue.meta.json` (~289 tok)
- `random.data.json` (~13214 tok)
- `random.meta.json` (~312 tok)
- `re.data.json` (~77300 tok)
- `re.meta.json` (~328 tok)
- `reprlib.data.json` (~5374 tok)
- `reprlib.meta.json` (~296 tok)
- `resource.data.json` (~13441 tok)
- `resource.meta.json` (~226 tok)
- `rlcompleter.data.json` (~1866 tok)
- `rlcompleter.meta.json` (~195 tok)
- `secrets.data.json` (~2200 tok)
- `secrets.meta.json` (~241 tok)
- `select.data.json` (~7917 tok)
- `select.meta.json` (~278 tok)
- `selectors.data.json` (~15634 tok)
- `selectors.meta.json` (~280 tok)
- `shlex.data.json` (~7744 tok)
- `shlex.meta.json` (~310 tok)
- `shutil.data.json` (~31268 tok)
- `shutil.meta.json` (~310 tok)
- `signal.data.json` (~20204 tok)
- `signal.meta.json` (~293 tok)
- `socket.data.json` (~43507 tok)
- `socket.meta.json` (~344 tok)
- `socketserver.data.json` (~19674 tok)
- `socketserver.meta.json` (~344 tok)
- `sre_compile.data.json` (~4299 tok)
- `sre_compile.meta.json` (~229 tok)
- `sre_constants.data.json` (~9214 tok)
- `sre_constants.meta.json` (~263 tok)
- `sre_parse.data.json` (~16268 tok)
- `sre_parse.meta.json` (~313 tok)
- `ssl.data.json` (~72506 tok)
- `ssl.meta.json` (~357 tok)
- `stat.data.json` (~4167 tok)
- `stat.meta.json` (~240 tok)
- `statistics.data.json` (~21974 tok)
- `statistics.meta.json` (~330 tok)
- `struct.data.json` (~1004 tok)
- `struct.meta.json` (~224 tok)
- `subprocess.data.json` (~71689 tok)
- `subprocess.meta.json` (~296 tok)
- `sysconfig.data.json` — Declares sysconfig (~6204 tok)
- `sysconfig.meta.json` (~246 tok)
- `tarfile.data.json` (~90239 tok)
- `tarfile.meta.json` (~374 tok)
- `tempfile.data.json` (~68472 tok)
- `tempfile.meta.json` (~326 tok)
- `termios.data.json` (~16064 tok)
- `termios.meta.json` (~260 tok)
- `textwrap.data.json` (~6257 tok)
- `textwrap.meta.json` (~227 tok)
- `threading.data.json` (~21086 tok)
- `threading.meta.json` (~313 tok)
- `time.data.json` (~13771 tok)
- `time.meta.json` (~242 tok)
- `timeit.data.json` (~3906 tok)
- `timeit.meta.json` (~246 tok)
- `token.data.json` (~5040 tok)
- `token.meta.json` (~224 tok)
- `tokenize.data.json` (~17051 tok)
- `tokenize.meta.json` (~310 tok)
- `tomllib.data.json` (~1852 tok)
- `tomllib.meta.json` (~278 tok)
- `traceback.data.json` (~23183 tok)
- `traceback.meta.json` (~280 tok)
- `tty.data.json` (~2157 tok)
- `tty.meta.json` (~274 tok)
- `types.data.json` (~109702 tok)
- `types.meta.json` (~322 tok)
- `typing_extensions.data.json` (~59086 tok)
- `typing_extensions.meta.json` (~333 tok)
- `typing.data.json` (~174485 tok)
- `typing.meta.json` (~313 tok)
- `unicodedata.data.json` (~18573 tok)
- `unicodedata.meta.json` (~246 tok)
- `uuid.data.json` (~10869 tok)
- `uuid.meta.json` (~258 tok)
- `warnings.data.json` (~9736 tok)
- `warnings.meta.json` (~311 tok)
- `weakref.data.json` (~98400 tok)
- `weakref.meta.json` (~297 tok)
- `zipimport.data.json` — Declares zipimport (~5612 tok)
- `zipimport.meta.json` (~342 tok)
- `zlib.data.json` (~8695 tok)
- `zlib.meta.json` (~258 tok)

## backend/.mypy_cache/3.11/_typeshed/

- `__init__.data.json` (~41722 tok)
- `__init__.meta.json` (~314 tok)
- `importlib.data.json` (~2259 tok)
- `importlib.meta.json` (~273 tok)
- `wsgi.data.json` (~1396 tok)
- `wsgi.meta.json` (~286 tok)

## backend/.mypy_cache/3.11/aiohappyeyeballs/

- `__init__.data.json` (~1023 tok)
- `__init__.meta.json` (~256 tok)
- `_staggered.data.json` (~2829 tok)
- `_staggered.meta.json` (~267 tok)
- `impl.data.json` (~2286 tok)
- `impl.meta.json` (~378 tok)
- `types.data.json` (~1010 tok)
- `types.meta.json` (~211 tok)
- `utils.data.json` (~2438 tok)
- `utils.meta.json` (~249 tok)

## backend/.mypy_cache/3.11/aiohttp/

- `__init__.data.json` (~4839 tok)
- `__init__.meta.json` (~525 tok)
- `_cookie_helpers.data.json` (~3226 tok)
- `_cookie_helpers.meta.json` (~262 tok)
- `abc.data.json` (~19707 tok)
- `abc.data.json.8d7e5de29c1a5a17` (~0 tok)
- `abc.meta.json` (~555 tok)
- `base_protocol.data.json` (~4243 tok)
- `base_protocol.data.json.5405b51bba137851` (~0 tok)
- `base_protocol.meta.json` (~364 tok)
- `client_exceptions.data.json` (~25038 tok)
- `client_exceptions.data.json.ff305954fddc7abc` (~0 tok)
- `client_exceptions.meta.json` (~468 tok)
- `client_middleware_digest_auth.data.json` (~5268 tok)
- `client_middleware_digest_auth.data.json.9073e9b995882012` (~0 tok)
- `client_middleware_digest_auth.meta.json` (~523 tok)
- `client_middlewares.data.json` (~1608 tok)
- `client_middlewares.data.json.ac988d9bbd0962ad` (~0 tok)
- `client_middlewares.meta.json` (~236 tok)
- `client_proto.data.json` (~9297 tok)
- `client_proto.data.json.fa78e2e42ead6372` (~0 tok)
- `client_proto.meta.json` (~500 tok)
- `client_reqrep.data.json` (~60672 tok)
- `client_reqrep.data.json.51c9e53a82ad2b7e` (~0 tok)
- `client_reqrep.meta.json` (~1250 tok)
- `client_ws.data.json` (~17898 tok)
- `client_ws.data.json.44da63f2091c4178` (~0 tok)
- `client_ws.meta.json` (~698 tok)
- `client.data.json` (~50848 tok)
- `client.meta.json` (~1213 tok)
- `compression_utils.data.json` (~18769 tok)
- `compression_utils.meta.json` (~334 tok)
- `connector.data.json` (~37395 tok)
- `connector.data.json.b659a5ebb2c2f84f` (~0 tok)
- `connector.meta.json` (~1006 tok)
- `cookiejar.data.json` (~11530 tok)
- `cookiejar.data.json.8dbaa7d37686ba8f` (~0 tok)
- `cookiejar.meta.json` (~692 tok)
- `formdata.data.json` (~3688 tok)
- `formdata.data.json.dccd68b959d97183` (~0 tok)
- `formdata.meta.json` (~440 tok)
- `hdrs.data.json` (~7271 tok)
- `hdrs.meta.json` (~264 tok)
- `helpers.data.json` (~54362 tok)
- `helpers.data.json.aa19611c6c383450` (~0 tok)
- `helpers.meta.json` (~913 tok)
- `http_exceptions.data.json` (~8028 tok)
- `http_exceptions.data.json.c8dbca19067d4d0a` (~0 tok)
- `http_exceptions.meta.json` (~306 tok)
- `http_parser.data.json` (~40995 tok)
- `http_parser.data.json.b383c6279bf85a0a` (~0 tok)
- `http_parser.meta.json` (~607 tok)
- `http_websocket.data.json` (~1206 tok)
- `http_websocket.data.json.c385f9ce4d21cc10` (~0 tok)
- `http_websocket.meta.json` (~297 tok)
- `http_writer.data.json` (~13393 tok)
- `http_writer.data.json.0a1e6225712c0abe` (~0 tok)
- `http_writer.meta.json` (~483 tok)
- `http.data.json` (~1796 tok)
- `http.data.json.bd9c98b98ddd1c3f` (~0 tok)
- `http.meta.json` (~367 tok)
- `log.data.json` (~885 tok)
- `log.meta.json` (~205 tok)
- `multipart.data.json` (~29301 tok)
- `multipart.data.json.832f5ed70b6c77f0` (~0 tok)
- `multipart.meta.json` (~731 tok)
- `payload_streamer.data.json` (~5464 tok)
- `payload_streamer.data.json.0e763805aff8f3b7` (~0 tok)
- `payload_streamer.meta.json` (~377 tok)
- `payload.data.json` (~29832 tok)
- `payload.data.json.6d33c4528817b869` (~0 tok)
- `payload.meta.json` (~702 tok)
- `resolver.data.json` (~6427 tok)
- `resolver.data.json.ca9dd66844b88383` (~0 tok)
- `resolver.meta.json` (~364 tok)
- `streams.data.json` (~26511 tok)
- `streams.data.json.e328c34595515b30` (~0 tok)
- `streams.meta.json` (~426 tok)
- `tcp_helpers.data.json` (~1173 tok)
- `tcp_helpers.meta.json` (~279 tok)
- `tracing.data.json` (~81423 tok)
- `tracing.data.json.c0c94e238a9c8e0f` (~0 tok)
- `tracing.meta.json` (~438 tok)
- `typedefs.data.json` (~5952 tok)
- `typedefs.data.json.2028ffd41793f03b` (~0 tok)
- `typedefs.meta.json` (~442 tok)
- `web_app.data.json` (~29958 tok)
- `web_app.meta.json` (~809 tok)
- `web_exceptions.data.json` (~33160 tok)
- `web_exceptions.meta.json` (~430 tok)
- `web_fileresponse.data.json` (~8168 tok)
- `web_fileresponse.meta.json` (~598 tok)
- `web_log.data.json` (~13817 tok)
- `web_log.meta.json` (~379 tok)
- `web_middlewares.data.json` (~2472 tok)
- `web_middlewares.meta.json` (~406 tok)
- `web_protocol.data.json` (~18571 tok)
- `web_protocol.meta.json` (~1085 tok)
- `web_request.data.json` (~32475 tok)
- `web_request.meta.json` (~1006 tok)
- `web_response.data.json` (~29333 tok)
- `web_response.meta.json` (~770 tok)
- `web_routedef.data.json` (~20321 tok)
- `web_routedef.meta.json` (~413 tok)
- `web_runner.data.json` (~19414 tok)
- `web_runner.meta.json` (~645 tok)
- `web_server.data.json` (~4647 tok)
- `web_server.meta.json` (~535 tok)
- `web_urldispatcher.data.json` (~61538 tok)
- `web_urldispatcher.meta.json` (~778 tok)
- `web_ws.data.json` (~20859 tok)
- `web_ws.meta.json` (~875 tok)
- `web.data.json` (~8002 tok)
- `web.data.json.55886f34c69f7dad` (~0 tok)
- `web.meta.json` (~761 tok)
- `worker.data.json` (~5743 tok)
- `worker.meta.json` (~674 tok)

## backend/.mypy_cache/3.11/aiohttp/_websocket/

- `__init__.data.json` (~547 tok)
- `__init__.meta.json` (~195 tok)
- `helpers.data.json` (~3736 tok)
- `helpers.data.json.a7582e386ff2d82e` (~0 tok)
- `helpers.meta.json` (~337 tok)
- `models.data.json` (~13828 tok)
- `models.meta.json` (~265 tok)
- `reader_py.data.json` (~10640 tok)
- `reader_py.data.json.18ac3567d00c4fbb` (~0 tok)
- `reader_py.meta.json` (~483 tok)
- `reader.data.json` (~797 tok)
- `reader.data.json.0cd731717b38e9ec` (~0 tok)
- `reader.meta.json` (~296 tok)
- `writer.data.json` (~4943 tok)
- `writer.data.json.90efa64bdab5afa6` (~0 tok)
- `writer.meta.json` (~497 tok)

## backend/.mypy_cache/3.11/aiosignal/

- `__init__.data.json` (~5190 tok)
- `__init__.meta.json` (~259 tok)

## backend/.mypy_cache/3.11/annotated_doc/

- `__init__.data.json` (~626 tok)
- `__init__.meta.json` (~212 tok)
- `main.data.json` (~1593 tok)
- `main.meta.json` (~193 tok)

## backend/.mypy_cache/3.11/annotated_types/

- `__init__.data.json` (~31528 tok)
- `__init__.meta.json` (~312 tok)

## backend/.mypy_cache/3.11/anyio/

- `__init__.data.json` (~3546 tok)
- `__init__.meta.json` (~516 tok)
- `from_thread.data.json` (~33209 tok)
- `from_thread.meta.json` (~559 tok)
- `lowlevel.data.json` (~13484 tok)
- `lowlevel.meta.json` (~332 tok)
- `to_thread.data.json` (~2459 tok)
- `to_thread.meta.json` (~337 tok)

## backend/.mypy_cache/3.11/anyio/_core/

- `__init__.data.json` (~529 tok)
- `__init__.meta.json` (~159 tok)
- `_contextmanagers.data.json` (~11057 tok)
- `_contextmanagers.meta.json` (~264 tok)
- `_eventloop.data.json` (~5785 tok)
- `_eventloop.meta.json` (~446 tok)
- `_exceptions.data.json` (~6384 tok)
- `_exceptions.meta.json` (~280 tok)
- `_fileio.data.json` (~42380 tok)
- `_fileio.meta.json` (~418 tok)
- `_resources.data.json` (~846 tok)
- `_resources.meta.json` (~237 tok)
- `_signals.data.json` (~899 tok)
- `_signals.meta.json` (~252 tok)
- `_sockets.data.json` (~20066 tok)
- `_sockets.meta.json` (~676 tok)
- `_streams.data.json` (~3264 tok)
- `_streams.meta.json` (~263 tok)
- `_subprocesses.data.json` (~3120 tok)
- `_subprocesses.meta.json` (~391 tok)
- `_synchronization.data.json` (~41892 tok)
- `_synchronization.meta.json` (~438 tok)
- `_tasks.data.json` (~6621 tok)
- `_tasks.meta.json` (~317 tok)
- `_tempfile.data.json` (~36626 tok)
- `_tempfile.meta.json` (~455 tok)
- `_testing.data.json` (~3569 tok)
- `_testing.meta.json` (~250 tok)
- `_typedattr.data.json` (~7150 tok)
- `_typedattr.meta.json` (~252 tok)

## backend/.mypy_cache/3.11/anyio/abc/

- `__init__.data.json` (~2072 tok)
- `__init__.meta.json` (~428 tok)
- `_eventloop.data.json` — Declares of (~38922 tok)
- `_eventloop.meta.json` (~487 tok)
- `_resources.data.json` (~2578 tok)
- `_resources.meta.json` (~226 tok)
- `_sockets.data.json` (~14994 tok)
- `_sockets.meta.json` (~493 tok)
- `_streams.data.json` (~16840 tok)
- `_streams.meta.json` (~342 tok)
- `_subprocesses.data.json` (~4868 tok)
- `_subprocesses.meta.json` (~268 tok)
- `_tasks.data.json` (~7610 tok)
- `_tasks.meta.json` (~315 tok)
- `_testing.data.json` (~5779 tok)
- `_testing.meta.json` (~244 tok)

## backend/.mypy_cache/3.11/anyio/streams/

- `__init__.data.json` (~534 tok)
- `__init__.meta.json` (~160 tok)
- `memory.data.json` (~28422 tok)
- `memory.meta.json` (~489 tok)
- `stapled.data.json` (~15784 tok)
- `stapled.meta.json` (~362 tok)
- `tls.data.json` (~15786 tok)
- `tls.meta.json` (~558 tok)

## backend/.mypy_cache/3.11/app/

- `api.data.json` (~441 tok)
- `api.meta.json` (~145 tok)
- `celery_app.data.json` (~1239 tok)
- `celery_app.meta.json` (~358 tok)
- `database.data.json` (~2415 tok)
- `database.meta.json` (~1091 tok)
- `limiter.data.json` (~1035 tok)
- `limiter.meta.json` (~220 tok)
- `main_minimal.data.json` (~5137 tok)
- `main_minimal.meta.json` (~1879 tok)
- `main.data.json` (~10349 tok)
- `main.meta.json` (~2198 tok)
- `middleware.data.json` (~457 tok)
- `middleware.meta.json` (~149 tok)
- `network_utils.data.json` (~9304 tok)
- `network_utils.meta.json` (~701 tok)
- `performance.data.json` (~3255 tok)
- `performance.meta.json` (~906 tok)
- `services.data.json` (~452 tok)
- `services.meta.json` (~148 tok)
- `utils.data.json` (~446 tok)
- `utils.meta.json` (~146 tok)

## backend/.mypy_cache/3.11/app/api/

- `admin.data.json` (~12884 tok)
- `admin.meta.json` (~1918 tok)
- `auth.data.json` (~9206 tok)
- `auth.meta.json` (~1884 tok)
- `chat.data.json` (~5089 tok)
- `chat.meta.json` (~1350 tok)
- `collections.data.json` (~12562 tok)
- `collections.meta.json` (~1634 tok)
- `deps.data.json` (~4176 tok)
- `deps.meta.json` (~1119 tok)
- `documents.data.json` (~11391 tok)
- `documents.meta.json` (~1703 tok)
- `graph_rag.data.json` (~9485 tok)
- `graph_rag.meta.json` (~1418 tok)
- `health.data.json` (~3322 tok)
- `health.meta.json` (~1549 tok)
- `knowledge_graph.data.json` (~9704 tok)
- `knowledge_graph.meta.json` (~1520 tok)
- `multi_agent.data.json` (~9704 tok)
- `multi_agent.meta.json` (~1417 tok)
- `reports.data.json` (~2084 tok)
- `reports.meta.json` (~926 tok)
- `search.data.json` (~3233 tok)
- `search.meta.json` (~1536 tok)
- `smart_folders.data.json` (~4195 tok)
- `smart_folders.meta.json` (~1093 tok)

## backend/.mypy_cache/3.11/app/core/

- `__init__.data.json` (~510 tok)
- `__init__.meta.json` (~146 tok)
- `config.data.json` (~8241 tok)
- `config.meta.json` (~597 tok)
- `redis_url.data.json` (~694 tok)
- `redis_url.meta.json` (~215 tok)

## backend/.mypy_cache/3.11/app/middleware/

- `csrf.data.json` (~2096 tok)
- `csrf.data.json.2028a8b294a1f829` (~0 tok)
- `csrf.meta.json` (~405 tok)
- `rls.data.json` (~1200 tok)
- `rls.meta.json` (~746 tok)
- `transaction.data.json` (~1296 tok)
- `transaction.meta.json` (~374 tok)

## backend/.mypy_cache/3.11/app/models/

- `__init__.data.json` (~1434 tok)
- `__init__.meta.json` (~358 tok)
- `audit_log.data.json` (~646 tok)
- `audit_log.meta.json` (~202 tok)
- `audit.data.json` (~4203 tok)
- `audit.meta.json` (~811 tok)
- `base.data.json` (~3320 tok)
- `base.meta.json` (~744 tok)
- `chat.data.json` (~5679 tok)
- `chat.meta.json` (~840 tok)
- `collection.data.json` (~10140 tok)
- `collection.meta.json` (~902 tok)
- `deferred_query.data.json` (~4042 tok)
- `deferred_query.meta.json` (~611 tok)
- `document.data.json` (~11561 tok)
- `document.meta.json` (~952 tok)
- `failed_task.data.json` (~2600 tok)
- `failed_task.meta.json` (~715 tok)
- `knowledge_graph.data.json` (~13400 tok)
- `knowledge_graph.meta.json` (~898 tok)
- `processing.data.json` (~5450 tok)
- `processing.meta.json` (~866 tok)
- `smart_folder.data.json` (~2126 tok)
- `smart_folder.meta.json` (~880 tok)
- `user.data.json` (~3144 tok)
- `user.meta.json` (~793 tok)

## backend/.mypy_cache/3.11/app/schemas/

- `__init__.data.json` (~3500 tok)
- `__init__.meta.json` (~339 tok)
- `admin.data.json` (~43302 tok)
- `admin.meta.json` (~394 tok)
- `auth.data.json` (~7823 tok)
- `auth.meta.json` (~215 tok)
- `chat.data.json` (~26468 tok)
- `chat.meta.json` (~455 tok)
- `collection.data.json` (~83732 tok)
- `collection.meta.json` (~459 tok)
- `document.data.json` (~43892 tok)
- `document.meta.json` (~457 tok)
- `pagination.data.json` (~14219 tok)
- `pagination.meta.json` (~479 tok)
- `reports.data.json` (~6148 tok)
- `reports.meta.json` (~217 tok)
- `search.data.json` (~10580 tok)
- `search.meta.json` (~424 tok)
- `token.data.json` (~8400 tok)
- `token.meta.json` (~216 tok)
- `user.data.json` (~16988 tok)
- `user.meta.json` (~421 tok)

## backend/.mypy_cache/3.11/app/services/

- `alert_service.data.json` (~3642 tok)
- `alert_service.meta.json` (~301 tok)
- `auto_tagging_service.data.json` (~4323 tok)
- `auto_tagging_service.meta.json` (~853 tok)
- `base_llm_service.data.json` (~2403 tok)
- `base_llm_service.meta.json` (~206 tok)
- `cache_monitor.data.json` (~8911 tok)
- `cache_monitor.meta.json` (~340 tok)
- `chat_service.data.json` (~5837 tok)
- `chat_service.meta.json` (~1406 tok)
- `collection_chat_service.data.json` (~4564 tok)
- `collection_chat_service.meta.json` (~1109 tok)
- `collection_service.data.json` (~5041 tok)
- `collection_service.meta.json` (~1250 tok)
- `deduplication_service.data.json` (~5219 tok)
- `deduplication_service.meta.json` (~1039 tok)
- `deferred_query_service.data.json` (~5119 tok)
- `deferred_query_service.meta.json` (~376 tok)
- `dlq_service.data.json` (~2653 tok)
- `dlq_service.meta.json` (~1110 tok)
- `email_notifier.data.json` (~2666 tok)
- `email_notifier.meta.json` (~302 tok)
- `embedding_service.data.json` (~7506 tok)
- `embedding_service.meta.json` (~649 tok)
- `entity_extraction_service.data.json` — Declares of (~8038 tok)
- `entity_extraction_service.meta.json` (~1093 tok)
- `graph_rag_service.data.json` (~6417 tok)
- `graph_rag_service.meta.json` (~1119 tok)
- `intent_parser.data.json` (~8974 tok)
- `intent_parser.meta.json` (~464 tok)
- `kimi_service.data.json` (~4276 tok)
- `kimi_service.meta.json` (~726 tok)
- `knowledge_graph/__init__.py` — KG package: exports GraphNode, GraphEdge, GraphTraversalService, EntityExtractor, all enums (~150 tok)
- `knowledge_graph/extraction.py` — EntityExtractor: process_chunk, NER+spaCy (graceful fallback), _resolve_or_create (embedding dedup), financial rules, LLM edge inference; asyncpg, sowknow schema (~900 tok)
- `knowledge_graph/models.py` — Pydantic models: NodeType, EdgeType, ExtractionMethod, GraphNode, GraphEdge, PathResult, ConnectionQuery (~450 tok)
- `knowledge_graph/pool.py` — get_graph_pool() / close_graph_pool(): module-level asyncpg pool factory from DATABASE_URL (~120 tok)
- `knowledge_graph/traversal.py` — GraphTraversalService: resolve_entity, find_connections (BFS recursive CTE), get_neighbours; asyncpg, sowknow schema (~800 tok)
- `llm_router.data.json` (~9146 tok)
- `llm_router.meta.json` (~464 tok)
- `minimax_service.data.json` (~4215 tok)
- `minimax_service.meta.json` (~691 tok)
- `monitoring.data.json` (~17934 tok)
- `monitoring.data.json.979555f7a7a422f1` (~0 tok)
- `monitoring.meta.json` (~628 tok)
- `ocr_service.data.json` (~8214 tok)
- `ocr_service.meta.json` (~605 tok)
- `ollama_service.data.json` (~3246 tok)
- `ollama_service.meta.json` (~691 tok)
- `openrouter_service.data.json` (~6538 tok)
- `openrouter_service.meta.json` (~899 tok)
- `performance_service.data.json` (~5968 tok)
- `performance_service.meta.json` (~1015 tok)
- `pii_detection_service.data.json` (~3194 tok)
- `pii_detection_service.meta.json` (~310 tok)
- `progressive_revelation_service.data.json` (~6472 tok)
- `progressive_revelation_service.meta.json` (~1156 tok)
- `prometheus_metrics.data.json` (~8686 tok)
- `prometheus_metrics.meta.json` (~331 tok)
- `relationship_service.data.json` (~5156 tok)
- `relationship_service.meta.json` (~1066 tok)
- `report_service.data.json` (~4229 tok)

## backend/.mypy_cache/3.11/app/services/agents/

- `__init__.data.json` (~1050 tok)
- `__init__.meta.json` (~309 tok)
- `agent_orchestrator.data.json` (~17766 tok)
- `agent_orchestrator.meta.json` (~472 tok)
- `answer_agent.data.json` — Declares of (~12791 tok)
- `answer_agent.meta.json` (~410 tok)
- `clarification_agent.data.json` (~10620 tok)
- `clarification_agent.meta.json` (~363 tok)
- `researcher_agent.data.json` (~14076 tok)
- `researcher_agent.meta.json` (~487 tok)
- `verification_agent.data.json` (~11729 tok)
- `verification_agent.meta.json` (~382 tok)

## backend/alembic/versions/

- `023_add_graph_tables.py` — Add knowledge graph tables (graph_nodes, graph_edges, entity_synonyms) (~1280 tok)

## backend/app/

- `main_minimal.py` — API: 4 endpoints (~4794 tok)

## backend/app/api/

- `admin.py` — API: 7 endpoints (~10421 tok)
- `auth.py` — API: 2 endpoints (~9599 tok)
- `documents.py` — API: 1 endpoints (~13769 tok)
- `voice.py` — API: 2 endpoints (~1926 tok)

## backend/app/models/

- `pipeline.py` — Pipeline stage tracking model for guaranteed document processing. (~993 tok)

## backend/app/schemas/

- `admin.py` — SystemStats: validate_role_change, validate_password, validate_password (~1472 tok)

## backend/app/services/

- `whisper_service.py` — WhisperService: transcribe (~738 tok)

## backend/app/services/agents/

- `researcher_agent.py` — from: embedding_fn, research (~5514 tok)

## backend/app/services/knowledge_graph/

- `__init__.py` (~133 tok)
- `extraction.py` — EntityExtractor: process_chunk (~4937 tok)
- `models.py` — Pydantic: GraphNode (~1503 tok)
- `pool.py` — get_graph_pool, close_graph_pool (~475 tok)
- `traversal.py` — GraphTraversalService: resolve_entity, find_connections, get_neighbours (~3453 tok)

## backend/app/tasks/

- `pipeline_tasks.py` — _EmbedContinue: update_stage (~5675 tok)
- `voice_tasks.py` — transcribe_voice_note (~1072 tok)

## backend/embed_server/

- `requirements.txt` — Python dependencies (~31 tok)

## backend/tests/integration/

- `test_knowledge_graph.py` — TestGraphSchema: event_loop, pool, clean_graph, insert_node + 12 more (~6647 tok)

## backend/tests/unit/

- `test_admin_pipeline_stats.py` — Unit tests for /admin/pipeline-stats assembler logic. (~1117 tok)
- `test_graph_intent_detection.py` — TestIsGraphTraversalQuery: agent, test_en_link_between, test_en_connection_between, test_en_what_con (~1082 tok)
- `test_knowledge_graph_models.py` — TestNodeType: test_all_values_are_strings, test_financial_types_present, test_core_types_present, te (~1402 tok)
- `test_voice_stream.py` — TestGetMimeTypeOggNormalization: make_fernet, encrypt_bytes, test_application_ogg_normalized_to_audi (~6763 tok)
- `test_whisper_service.py` — TestWhisperService: test_transcribe_sync_returns_transcript, test_transcribe_sync_auto_language_pass (~906 tok)

## docs/superpowers/plans/

- `2026-04-12-bookmarks-mobile-overflow-fix.md` — Mobile Overflow Fix + Bookmarks Mobile Adaptation — Implementation Plan (~5592 tok)
- `2026-04-12-dashboard-live-pipeline.md` — Dashboard Live Pipeline Monitoring Implementation Plan (~6201 tok)
- `2026-04-12-nftables-permanent-fix.md` — nftables Permanent Fix Implementation Plan (~8783 tok)
- `2026-04-14-embed-server-extraction.md` — Embed Server Extraction Implementation Plan (~7543 tok)

## docs/superpowers/specs/

- `2026-04-12-bookmarks-mobile-overflow-fix-design.md` — Mobile Overflow Fix + Bookmarks Mobile Adaptation (~967 tok)
- `2026-04-12-dashboard-live-pipeline-design.md` — Dashboard Live Pipeline Monitoring — Design Spec (~1650 tok)
- `2026-04-12-nftables-permanent-fix-design.md` — Design Spec: Permanent nftables Stale-Rules Auto-Heal (~2998 tok)

## frontend/__tests__/

- `bookmarks.test.tsx` — Minimal mocks required by the page (~692 tok)

## frontend/app/

- `globals.css` — Styles: 55 rules, 27 vars (~2814 tok)

## frontend/app/[locale]/bookmarks/

- `page.tsx` — dynamic — renders form (~3728 tok)
- `utils.ts` — Exports parseDomain (~43 tok)

## frontend/app/[locale]/dashboard/

- `page.tsx` — API_BASE (~6352 tok)

## frontend/app/[locale]/journal/

- `page.tsx` — JournalPage (~4370 tok)

## frontend/app/[locale]/notes/

- `page.tsx` — dynamic — renders form (~5457 tok)

## frontend/hooks/

- `useVoiceRecorder.ts` — Exports RecordingState, useVoiceRecorder (~2468 tok)

## frontend/lib/

- `api.ts` — API client for SOWKNOW backend (~7002 tok)

## monitoring/guardian-hc/

- `Dockerfile` — Docker container definition (~358 tok)
- `guardian-hc.sowknow4.yml` — Guardian HC v2.0 -- SOWKNOW4 Configuration (~1653 tok)

## monitoring/guardian-hc/guardian_hc/

- `config.py` — class: load_config (~1585 tok)
- `core.py` — class: can_restart, record_attempt, to_dict, from_dict + 6 more (~11498 tok)
- `daily_report.py` (~5381 tok)
- `dashboard.py` — DashboardServer: start, handle_dashboard, handle_metrics, handle_send_report (~758 tok)

## monitoring/guardian-hc/guardian_hc/checks/

- `config_drift.py` — ConfigDriftChecker: check (~303 tok)
- `network_health.py` — NetworkHealthChecker: check (~2096 tok)

## monitoring/guardian-hc/guardian_hc/healers/

- `network_healer.py` — NetworkHealer: heal (~1444 tok)

## monitoring/guardian-hc/guardian_hc/plugins/

- `probes.py` — ProbesPlugin — deep application probes for Guardian (Watcher role). (~8636 tok)

## monitoring/guardian-hc/guardian_hc/runbooks/

- `__init__.py` (~41 tok)
- `engine.py` — class: to_log_dict, loaded, find, execute (~3600 tok)

## monitoring/guardian-hc/runbooks/

- `backend_unhealthy.yml` (~1001 tok)
- `celery_completion.yml` (~1173 tok)
- `disk_critical.yml` (~839 tok)
- `pipeline_stuck.yml` (~1017 tok)
- `redis_deep.yml` (~934 tok)

## monitoring/guardian-hc/scripts/

- `watchdog.sh` — ############################################################################## (~2955 tok)

## monitoring/guardian-hc/tests/

- `test_network_healer.py` — Tests for NetworkHealer.heal() — surgical per-handle deletion. (~1442 tok)
- `test_network_health.py` — Tests for NetworkHealthChecker._find_stale_nftables_bridges(). (~2202 tok)
