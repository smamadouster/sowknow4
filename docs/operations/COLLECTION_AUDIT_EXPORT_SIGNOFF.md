# Collection Audit Export — Compliance Sign-off

Scope: Collection Orchestrator audit trail (FR8.1), audit export endpoint,
retention & privacy controls (FR8.4), and the reproducibility check (FR8.5).
Audience: compliance / DPO / ops signing off on the audit export feature.

## 1. Audit export format spec (spec §2.7)

Endpoint: `GET /collection-requests/{request_id}/audit?format=json|csv`
(owner-scoped; a foreign request id is indistinguishable from a missing one).

Every exported event carries the spec §2.7 field set:

| Field | JSON | CSV column | Notes |
|---|---|---|---|
| `id` | ✓ | 1 | event UUID |
| `timestamp` | ✓ | 2 | ISO-8601 UTC |
| `stage` | ✓ | 3 | clarify / plan / retrieve / process / extract / analyse / summarise / validate / package / export / cancel |
| `action` | ✓ | 4 | e.g. `execute_search_plan`, `claims_validated`, `audit_export` |
| `status` | ✓ | 5 | `success` / `failure` |
| `input_ref` | ✓ | 6 | e.g. `items:120`, `factset:<uuid>` |
| `output_ref` | ✓ | 7 | e.g. `deliverable:<uuid>` |
| `component_version` | ✓ | 8 | e.g. `collection-orchestrator 1.0.0` |
| `duration_ms` | ✓ | 9 | per-stage latency (feeds FR8.2 metrics) |
| `detail` | ✓ | 10 | JSON blob (CSV: JSON-encoded string) |
| `user_id` | ✓ | 11 | raw UUID, or salted pseudonym when pseudonymisation is on (§3) |

JSON envelope: `{request_id, pseudonymised, events: [...]}` — the
`pseudonymised` flag tells the consumer how to read `user_id`.
The trail is append-only (`collection_audit_events` has no update path);
the only deletion path is the FR8.4 retention purge (§3).

## 2. Access control model

- [ ] Export endpoints are **owner-only**: `/{id}/audit`,
      `/{id}/deliverable`, `/{id}/deliverable/export`,
      `/{id}/deliverable/diff`, `/{id}/deliverable/reproducibility` all
      resolve the SmartFolder with `user_id == current_user`; non-owners
      get 404 (no existence leak).
- [ ] Every audit export is itself **audited**: an `export` /
      `audit_export` event with format + event count is appended before the
      response is served.
- [ ] The **metrics overview** (`GET /collection-requests/metrics/overview`)
      is restricted to ADMIN / SUPERUSER (`require_superuser_or_admin`);
      plain users get 403.
- [ ] Admin access to user content stays on the existing admin routes and
      is covered by the platform-wide admin audit; the collection audit
      export does not bypass ownership.
- [ ] Deliverable links are permission-bound (`links_permission_bound:
      true`) — internal URIs re-checked at navigation.

## 3. Retention & privacy knobs (FR8.4)

| Setting | Default | Meaning |
|---|---|---|
| `COLLECTION_AUDIT_RETENTION_DAYS` | `2555` (7 years) | Events older than this are deleted by the daily purge |
| `COLLECTION_AUDIT_PSEUDONYMISE` | `false` | When `true`, `user_id` in audit exports is replaced by `user_<hmac>` — HMAC-SHA256(user_id, key=`JWT_SECRET`), stable across exports, reversible only with the server secret |

- Purge: `purge_expired_audit_events(db)` (single bounded `DELETE`),
  scheduled daily 03:30 UTC via Celery beat entry
  `collection-audit-retention` →
  `app.tasks.collection_request_tasks.purge_collection_audit_events_task`
  (queue `scheduled`). Manual run:
  `celery -A app.celery_app call app.tasks.collection_request_tasks.purge_collection_audit_events_task`.
- [ ] Retention period reviewed against legal hold requirements (7-year
      default matches SYSCOHADA record-keeping norms).
- [ ] Pseudonymisation enabled if exports leave the platform boundary
      (off by default — internal ops need real user ids).
- [ ] Pseudonym salt is the server-side `JWT_SECRET`; rotating that secret
      changes all pseudonyms (documented, acceptable — exports are
      point-in-time artifacts).

## 4. Reproducibility check (FR8.5)

`GET /collection-requests/{id}/deliverable/reproducibility` (owner-scoped):

1. Loads the stored FactSet (highest version) and the `analysis_types`
   from `confirmed_params`.
2. Re-runs the deterministic `AnalysisEngine` over the above-threshold
   facts with the thresholds recorded on each stored `AnalysisResult`.
3. Compares stored vs fresh outputs with exact JSON equality.

Response: `{matches, differences, code_version_stored,
code_version_current, note}`.

- `matches: true` — stored analysis reproduces exactly.
- `matches: false` — divergence; `differences[]` carries both outputs.
  Investigate as a data-integrity incident.
- `matches: null` — `ANALYSIS_CODE_VERSION` changed since the stored run
  (current: see `analysis_engine.ANALYSIS_CODE_VERSION`); exact comparison
  is not meaningful. Re-run the request (`POST /{id}/rerun`) to produce a
  deliverable under the current code version.

- [ ] Reproducibility spot-check performed on at least one completed
      request per release that bumps `ANALYSIS_CODE_VERSION`.

## 5. Sign-off checklist

- [ ] Export field set matches §1 for both JSON and CSV.
- [ ] Owner-only access verified (foreign id → 404); export itself audited.
- [ ] Metrics overview restricted to ADMIN/SUPERUSER; active alerts logged
      at WARNING (guardian-hc log scraping hook).
- [ ] Retention purge scheduled (beat entry present) and tested on a
      disposable dataset before first production run.
- [ ] Pseudonymisation behaviour verified with
      `COLLECTION_AUDIT_PSEUDONYMISE=true` on staging.
- [ ] Reproducibility endpoint returns `matches: true` for a known-good
      request.
- [ ] FR7.2 output sanitisation active on all rendering paths (in-app view,
      PDF, DOCX) — injection corpus + sanitiser tests green.
