# Dashboard Live Pipeline Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 broken field-name mismatches in the admin dashboard, replace the fake uploads chart with real DB data, and add a live pipeline funnel panel with per-stage counts and throughput rates, polling every 10s.

**Architecture:** Two new backend endpoints (`GET /admin/pipeline-stats` and `GET /admin/uploads-history`) query `pipeline_stages` and `documents` tables with efficient GROUP BY queries. Frontend fixes field name mismatches, splits into two polling intervals (10s for pipeline/queue, 60s for slow stats), and adds an inline `PipelinePanel` section.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async (backend); Next.js 14, TypeScript, Recharts (frontend); PostgreSQL `sowknow` schema.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `backend/app/schemas/admin.py` | Modify | Add `PipelineStageStats`, `PipelineStatsResponse`, `UploadsHistoryPoint`, `UploadsHistoryResponse` |
| `backend/app/api/admin.py` | Modify | Add `GET /admin/pipeline-stats` and `GET /admin/uploads-history` endpoints |
| `backend/tests/unit/test_admin_pipeline_stats.py` | Create | Unit tests for pipeline-stats logic |
| `frontend/app/[locale]/dashboard/page.tsx` | Modify | Fix interfaces + field reads; add pipeline state + fetch; add `PipelinePanel` section; replace fake chart; split polling |

---

## Task 1: Add Pydantic schemas

**Files:**
- Modify: `backend/app/schemas/admin.py`

- [ ] **Step 1: Add the four new schemas at the bottom of `backend/app/schemas/admin.py`**

Append after the `PasswordReset` class:

```python
class PipelineStageStats(BaseModel):
    """Counts and throughput for a single pipeline stage."""
    stage: str
    pending: int
    running: int
    failed: int
    throughput_per_hour: int
    throughput_per_10min: int


class PipelineStatsResponse(BaseModel):
    """Full pipeline funnel snapshot."""
    stages: list[PipelineStageStats]
    total_active: int          # sum of all running counts
    bottleneck_stage: str | None  # stage with highest pending count, or None


class UploadsHistoryPoint(BaseModel):
    day: str   # "YYYY-MM-DD"
    count: int


class UploadsHistoryResponse(BaseModel):
    history: list[UploadsHistoryPoint]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/admin.py
git commit -m "feat(admin): add PipelineStatsResponse and UploadsHistoryResponse schemas"
```

---

## Task 2: Add `GET /admin/pipeline-stats` endpoint

**Files:**
- Modify: `backend/app/api/admin.py`

The endpoint queries `sowknow.pipeline_stages` using the existing `PipelineStage` model (`app.models.pipeline`). Stages are: `uploaded ocr chunked embedded indexed articles entities enriched`. Statuses relevant here: `pending`, `running`, `failed` (for the funnel) and `completed` (for throughput).

- [ ] **Step 1: Add the import for `PipelineStage` and `StageEnum` / `StageStatus` at the top of `backend/app/api/admin.py`**

Find the existing imports block and add:
```python
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
```

Also add `PipelineStatsResponse` to the existing schemas import:
```python
from app.schemas.admin import (
    AdminStatsResponse,
    AnomalyBucketResponse,
    AnomalyDocument,
    AuditLogEntry,
    AuditLogResponse,
    DashboardResponse,
    PasswordReset,
    PipelineStatsResponse,
    QueueStats,
    SystemStats,
    UploadsHistoryResponse,
    UserCreateByAdmin,
    UserListResponse,
    UserManagementResponse,
    UserUpdateByAdmin,
)
```

- [ ] **Step 2: Add the endpoint after the `get_anomalies` function (before `get_dashboard`)**

```python
PIPELINE_STAGE_ORDER = [
    StageEnum.UPLOADED,
    StageEnum.OCR,
    StageEnum.CHUNKED,
    StageEnum.EMBEDDED,
    StageEnum.INDEXED,
    StageEnum.ARTICLES,
    StageEnum.ENTITIES,
    StageEnum.ENRICHED,
]


@router.get("/pipeline-stats", response_model=PipelineStatsResponse)
async def get_pipeline_stats(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
) -> PipelineStatsResponse:
    """Per-stage pipeline funnel with throughput rates (Admin only)."""
    # Query 1: active counts grouped by stage + status
    active_result = await db.execute(
        select(PipelineStage.stage, PipelineStage.status, func.count().label("cnt"))
        .where(PipelineStage.status.in_([StageStatus.PENDING, StageStatus.RUNNING, StageStatus.FAILED]))
        .group_by(PipelineStage.stage, PipelineStage.status)
    )
    active_rows = active_result.all()

    # Query 2: throughput — completed in last 1 hour
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    hourly_result = await db.execute(
        select(PipelineStage.stage, func.count().label("cnt"))
        .where(
            PipelineStage.status == StageStatus.COMPLETED,
            PipelineStage.completed_at >= one_hour_ago,
        )
        .group_by(PipelineStage.stage)
    )
    hourly_rows = {
        (row.stage if isinstance(row.stage, str) else row.stage.value): row.cnt
        for row in hourly_result.all()
    }

    # Query 3: throughput — completed in last 10 minutes
    ten_min_ago = datetime.utcnow() - timedelta(minutes=10)
    tenmin_result = await db.execute(
        select(PipelineStage.stage, func.count().label("cnt"))
        .where(
            PipelineStage.status == StageStatus.COMPLETED,
            PipelineStage.completed_at >= ten_min_ago,
        )
        .group_by(PipelineStage.stage)
    )
    tenmin_rows = {
        (row.stage if isinstance(row.stage, str) else row.stage.value): row.cnt
        for row in tenmin_result.all()
    }

    # Build per-stage counts map
    counts: dict[str, dict[str, int]] = {
        s.value: {"pending": 0, "running": 0, "failed": 0} for s in PIPELINE_STAGE_ORDER
    }
    for row in active_rows:
        stage_key = row.stage if isinstance(row.stage, str) else row.stage.value
        status_key = row.status if isinstance(row.status, str) else row.status.value
        if stage_key in counts and status_key in counts[stage_key]:
            counts[stage_key][status_key] = row.cnt

    stages = []
    for stage_enum in PIPELINE_STAGE_ORDER:
        key = stage_enum.value
        c = counts[key]
        stages.append(
            PipelineStageStats(
                stage=key,
                pending=c["pending"],
                running=c["running"],
                failed=c["failed"],
                throughput_per_hour=hourly_rows.get(key, 0),
                throughput_per_10min=tenmin_rows.get(key, 0),
            )
        )

    total_active = sum(s.running for s in stages)

    # Bottleneck: stage with highest pending count (ignore zero)
    max_pending = max((s.pending for s in stages), default=0)
    bottleneck = None
    if max_pending > 0:
        bottleneck = next(s.stage for s in stages if s.pending == max_pending)

    return PipelineStatsResponse(
        stages=stages,
        total_active=total_active,
        bottleneck_stage=bottleneck,
    )
```

- [ ] **Step 3: Import `PipelineStageStats` in the schemas import (it's needed inside the endpoint body)**

`PipelineStageStats` is already imported via `PipelineStatsResponse` import in Step 1 — but it's used directly in the endpoint. Add it to the import explicitly:

```python
from app.schemas.admin import (
    ...
    PipelineStageStats,
    PipelineStatsResponse,
    ...
)
```

- [ ] **Step 4: Verify the endpoint is routable**

```bash
cd /home/development/src/active/sowknow4/backend
python -c "from app.api.admin import router; routes = [r.path for r in router.routes]; print([r for r in routes if 'pipeline' in r])"
```

Expected output: `['/admin/pipeline-stats']`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/admin.py
git commit -m "feat(admin): add GET /admin/pipeline-stats endpoint"
```

---

## Task 3: Add `GET /admin/uploads-history` endpoint

**Files:**
- Modify: `backend/app/api/admin.py`

- [ ] **Step 1: Add the endpoint after `get_pipeline_stats`**

```python
@router.get("/uploads-history", response_model=UploadsHistoryResponse)
async def get_uploads_history(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
) -> UploadsHistoryResponse:
    """7-day real uploads history grouped by day (Admin only)."""
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    result = await db.execute(
        select(
            func.date(Document.created_at).label("day"),
            func.count().label("count"),
        )
        .where(Document.created_at >= seven_days_ago)
        .group_by(func.date(Document.created_at))
        .order_by(func.date(Document.created_at))
    )
    rows = result.all()

    history = [
        UploadsHistoryPoint(day=str(row.day), count=row.count)
        for row in rows
    ]
    return UploadsHistoryResponse(history=history)
```

- [ ] **Step 2: Verify endpoint is routable**

```bash
cd /home/development/src/active/sowknow4/backend
python -c "from app.api.admin import router; routes = [r.path for r in router.routes]; print([r for r in routes if 'uploads' in r])"
```

Expected output: `['/admin/uploads-history']`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/admin.py
git commit -m "feat(admin): add GET /admin/uploads-history endpoint with real 7-day data"
```

---

## Task 4: Write and run backend unit tests

**Files:**
- Create: `backend/tests/unit/test_admin_pipeline_stats.py`

These tests verify the assembler logic (stage ordering, bottleneck detection, zero-fill) without hitting the DB by constructing mock row objects.

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for /admin/pipeline-stats assembler logic."""
import pytest
from app.models.pipeline import StageEnum, StageStatus
from app.schemas.admin import PipelineStageStats, PipelineStatsResponse

PIPELINE_STAGE_ORDER = [
    StageEnum.UPLOADED,
    StageEnum.OCR,
    StageEnum.CHUNKED,
    StageEnum.EMBEDDED,
    StageEnum.INDEXED,
    StageEnum.ARTICLES,
    StageEnum.ENTITIES,
    StageEnum.ENRICHED,
]


def _build_response(active_rows, hourly_rows, tenmin_rows):
    """Replicate the assembler logic from the endpoint."""
    counts = {
        s.value: {"pending": 0, "running": 0, "failed": 0} for s in PIPELINE_STAGE_ORDER
    }
    for stage_key, status_key, cnt in active_rows:
        if stage_key in counts and status_key in counts[stage_key]:
            counts[stage_key][status_key] = cnt

    stages = []
    for stage_enum in PIPELINE_STAGE_ORDER:
        key = stage_enum.value
        c = counts[key]
        stages.append(
            PipelineStageStats(
                stage=key,
                pending=c["pending"],
                running=c["running"],
                failed=c["failed"],
                throughput_per_hour=hourly_rows.get(key, 0),
                throughput_per_10min=tenmin_rows.get(key, 0),
            )
        )

    total_active = sum(s.running for s in stages)
    max_pending = max((s.pending for s in stages), default=0)
    bottleneck = None
    if max_pending > 0:
        bottleneck = next(s.stage for s in stages if s.pending == max_pending)

    return PipelineStatsResponse(
        stages=stages,
        total_active=total_active,
        bottleneck_stage=bottleneck,
    )


class TestPipelineStatsAssembler:
    def test_returns_all_8_stages(self):
        result = _build_response([], {}, {})
        assert len(result.stages) == 8

    def test_stages_in_correct_order(self):
        result = _build_response([], {}, {})
        expected = [s.value for s in PIPELINE_STAGE_ORDER]
        assert [s.stage for s in result.stages] == expected

    def test_zero_fill_when_no_data(self):
        result = _build_response([], {}, {})
        for s in result.stages:
            assert s.pending == 0
            assert s.running == 0
            assert s.failed == 0
            assert s.throughput_per_hour == 0
            assert s.throughput_per_10min == 0

    def test_total_active_is_sum_of_running(self):
        active_rows = [
            ("embedded", "running", 5),
            ("ocr", "running", 2),
            ("chunked", "pending", 100),
        ]
        result = _build_response(active_rows, {}, {})
        assert result.total_active == 7

    def test_bottleneck_is_stage_with_highest_pending(self):
        active_rows = [
            ("embedded", "pending", 2200),
            ("ocr", "pending", 10),
            ("chunked", "pending", 50),
        ]
        result = _build_response(active_rows, {}, {})
        assert result.bottleneck_stage == "embedded"

    def test_bottleneck_none_when_all_pending_zero(self):
        active_rows = [("embedded", "running", 3)]
        result = _build_response(active_rows, {}, {})
        assert result.bottleneck_stage is None

    def test_throughput_mapped_correctly(self):
        result = _build_response(
            [],
            {"embedded": 45, "ocr": 100},
            {"embedded": 8},
        )
        embedded = next(s for s in result.stages if s.stage == "embedded")
        assert embedded.throughput_per_hour == 45
        assert embedded.throughput_per_10min == 8
        ocr = next(s for s in result.stages if s.stage == "ocr")
        assert ocr.throughput_per_hour == 100
        assert ocr.throughput_per_10min == 0

    def test_failed_count_populated(self):
        active_rows = [("ocr", "failed", 3)]
        result = _build_response(active_rows, {}, {})
        ocr = next(s for s in result.stages if s.stage == "ocr")
        assert ocr.failed == 3
```

- [ ] **Step 2: Run the tests**

```bash
cd /home/development/src/active/sowknow4/backend
python -m pytest tests/unit/test_admin_pipeline_stats.py -v
```

Expected output: all 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_admin_pipeline_stats.py
git commit -m "test(admin): unit tests for pipeline-stats assembler logic"
```

---

## Task 5: Fix frontend TypeScript interfaces and field reads

**Files:**
- Modify: `frontend/app/[locale]/dashboard/page.tsx`

- [ ] **Step 1: Replace the `Stats`, `QueueStats`, and `Anomaly` interfaces (lines 11–42)**

Replace the three interfaces with:

```typescript
interface Stats {
  total_documents: number;
  uploads_today: number;
  indexed_documents: number;
  public_documents: number;
  confidential_documents: number;
  total_users: number;
  active_sessions: number;
  processing_documents: number;
  error_documents: number;
}

interface QueueStats {
  pending_tasks: number;
  in_progress_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  average_wait_time: number | null;
  longest_running_task: string | null;
}

interface Anomaly {
  document_id: string;
  filename: string;
  bucket: string;
  status: string;
  error_message: string | null;
  stuck_duration_hours: number;
  created_at: string;
  last_task_type: string | null;
}
```

- [ ] **Step 2: Fix field reads in the render output**

Find and replace each occurrence (use exact strings to avoid mistakes):

| Old | New |
|-----|-----|
| `stats?.indexed_pages` | `stats?.indexed_documents` |
| `stats?.active_users_today` | `stats?.active_sessions` |
| `queueStats?.pending` | `queueStats?.pending_tasks` |
| `queueStats?.in_progress` | `queueStats?.in_progress_tasks` |
| `queueStats?.failed` | `queueStats?.failed_tasks` |
| `queueStats.in_progress / queueStats.total` | `queueStats.in_progress_tasks / (queueStats.pending_tasks + queueStats.in_progress_tasks + queueStats.failed_tasks)` |
| `anomaly.hours_stuck` | `anomaly.stuck_duration_hours` |
| `key={anomaly.id}` | `key={anomaly.document_id}` |

Queue total is now computed: replace any render of `queueStats?.total` with:
```typescript
{(queueStats ? queueStats.pending_tasks + queueStats.in_progress_tasks + queueStats.failed_tasks : '-')}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /home/development/src/active/sowknow4/frontend
npx tsc --noEmit 2>&1 | grep -i "dashboard"
```

Expected: no errors mentioning `dashboard/page.tsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/[locale]/dashboard/page.tsx
git commit -m "fix(dashboard): correct field name mismatches in Stats, QueueStats, Anomaly interfaces"
```

---

## Task 6: Add pipeline panel, real uploads chart, and two polling intervals

**Files:**
- Modify: `frontend/app/[locale]/dashboard/page.tsx`

- [ ] **Step 1: Add pipeline state types and state variables**

After the existing interface definitions, add the pipeline interfaces:

```typescript
interface PipelineStageData {
  stage: string;
  pending: number;
  running: number;
  failed: number;
  throughput_per_hour: number;
  throughput_per_10min: number;
}

interface PipelineStats {
  stages: PipelineStageData[];
  total_active: number;
  bottleneck_stage: string | null;
}
```

In the component body, add new state after the existing state declarations:

```typescript
const [pipelineStats, setPipelineStats] = useState<PipelineStats | null>(null);
const [uploadsHistory, setUploadsHistory] = useState<{ day: string; count: number }[]>([]);
const [lastPipelineUpdate, setLastPipelineUpdate] = useState<Date>(new Date());
```

Remove the existing `uploadsHistory` state declaration (it's being re-declared here with accurate typing).

- [ ] **Step 2: Replace the single `loadDashboard` function with two fetch functions**

Remove the existing `loadDashboard` function and its `useEffect`. Replace with:

```typescript
const loadSlowStats = async () => {
  try {
    const [statsRes, anomaliesRes, historyRes] = await Promise.all([
      fetch(`${API_BASE}/v1/admin/stats`, { credentials: 'include' }),
      fetch(`${API_BASE}/v1/admin/anomalies`, { credentials: 'include' }),
      fetch(`${API_BASE}/v1/admin/uploads-history`, { credentials: 'include' }),
    ]);

    if (statsRes.ok) setStats(await statsRes.json());
    if (anomaliesRes.ok) {
      const data = await anomaliesRes.json();
      setAnomalies(data.anomalies || data || []);
    }
    if (historyRes.ok) {
      const data = await historyRes.json();
      setUploadsHistory(data.history || []);
    }
    setLastUpdated(new Date());
  } catch (e) {
    console.error('Error loading slow stats:', e);
    setError(tCommon('error'));
  }
};

const loadLiveStats = async () => {
  try {
    const [queueRes, pipelineRes] = await Promise.all([
      fetch(`${API_BASE}/v1/admin/queue-stats`, { credentials: 'include' }),
      fetch(`${API_BASE}/v1/admin/pipeline-stats`, { credentials: 'include' }),
    ]);

    if (queueRes.ok) setQueueStats(await queueRes.json());
    if (pipelineRes.ok) setPipelineStats(await pipelineRes.json());
    setLastPipelineUpdate(new Date());
  } catch (e) {
    console.error('Error loading live stats:', e);
  }
};

useEffect(() => {
  setLoading(true);
  Promise.all([loadSlowStats(), loadLiveStats()]).finally(() => setLoading(false));

  const slowInterval = setInterval(loadSlowStats, 60_000);
  const liveInterval = setInterval(loadLiveStats, 10_000);
  return () => {
    clearInterval(slowInterval);
    clearInterval(liveInterval);
  };
}, []);
```

Also update the Refresh button's `onClick` to call both: `onClick={() => { loadSlowStats(); loadLiveStats(); }}`

- [ ] **Step 3: Fix the uploads chart — remove fake data generation**

Remove lines that generated fake history data (the `Array.from({ length: 7 }, ...)` block inside `loadDashboard`). The real data now comes from `loadSlowStats` → `uploads-history` endpoint.

Update the chart's `data` prop: the `UploadsPoint` format from the API matches `{ day: string, count: number }`. Update `XAxis dataKey` to `"day"` and `Area dataKey` to `"count"` (these may already match — verify they do).

- [ ] **Step 4: Add the PipelinePanel section**

Add this section in the JSX, between the Charts Row block and the Anomalies section:

```tsx
{/* Pipeline Funnel */}
<div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-8">
  <div className="flex items-center justify-between mb-4">
    <div className="flex items-center gap-3">
      <h2 className="text-lg font-semibold text-gray-900">Pipeline</h2>
      {pipelineStats && (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
          {pipelineStats.total_active} active
        </span>
      )}
    </div>
    <div className="text-xs text-gray-400">
      Updated {lastPipelineUpdate.toLocaleTimeString()}
    </div>
  </div>

  {pipelineStats ? (
    <div className="space-y-3">
      {(() => {
        const STAGE_LABELS: Record<string, string> = {
          uploaded: 'Uploaded',
          ocr: 'OCR',
          chunked: 'Chunking',
          embedded: 'Embedding',
          indexed: 'Indexing',
          articles: 'Articles',
          entities: 'Entities',
          enriched: 'Enriched',
        };
        const maxPending = Math.max(...pipelineStats.stages.map(s => s.pending), 1);

        return pipelineStats.stages.map((stage) => {
          const isBottleneck = stage.stage === pipelineStats.bottleneck_stage;
          const barWidth = Math.round((stage.pending / maxPending) * 100);

          return (
            <div
              key={stage.stage}
              className={`flex items-center gap-4 p-3 rounded-lg ${isBottleneck ? 'bg-amber-50 border border-amber-200' : 'bg-gray-50'}`}
            >
              {/* Stage label */}
              <div className="w-24 shrink-0">
                <span className="text-sm font-medium text-gray-700">
                  {STAGE_LABELS[stage.stage] ?? stage.stage}
                </span>
                {isBottleneck && (
                  <span className="ml-1 text-xs text-amber-600">⚡</span>
                )}
              </div>

              {/* Pending bar */}
              <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-2 rounded-full transition-all ${isBottleneck ? 'bg-amber-400' : 'bg-blue-400'}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>

              {/* Counts */}
              <div className="flex items-center gap-3 text-xs shrink-0">
                <span className="text-yellow-700 font-medium w-16 text-right">
                  {stage.pending.toLocaleString()} pending
                </span>
                <span className="text-blue-700 w-16 text-right">
                  {stage.running} running
                </span>
                {stage.failed > 0 && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                    {stage.failed} failed
                  </span>
                )}
                <span className="text-gray-400 w-28 text-right">
                  {stage.throughput_per_hour}/hr · {stage.throughput_per_10min}/10min
                </span>
              </div>
            </div>
          );
        });
      })()}
    </div>
  ) : (
    <div className="space-y-2">
      {[...Array(8)].map((_, i) => (
        <div key={i} className="h-10 bg-gray-100 rounded-lg animate-pulse" />
      ))}
    </div>
  )}
</div>
```

- [ ] **Step 5: Verify TypeScript compiles clean**

```bash
cd /home/development/src/active/sowknow4/frontend
npx tsc --noEmit 2>&1 | grep -i "dashboard"
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/[locale]/dashboard/page.tsx
git commit -m "feat(dashboard): add live pipeline funnel panel, real uploads chart, 10s polling"
```

---

## Task 7: End-to-end smoke test

- [ ] **Step 1: Run the backend tests suite to confirm nothing broke**

```bash
cd /home/development/src/active/sowknow4/backend
python -m pytest tests/unit/test_admin_pipeline_stats.py tests/unit/test_pipeline_model.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Check the new endpoints are registered in main**

```bash
cd /home/development/src/active/sowknow4/backend
python -c "
from app.api.admin import router
paths = [r.path for r in router.routes]
for p in paths:
    print(p)
" | grep -E "pipeline|uploads"
```

Expected output:
```
/admin/pipeline-stats
/admin/uploads-history
```

- [ ] **Step 3: Run frontend type check one final time**

```bash
cd /home/development/src/active/sowknow4/frontend
npx tsc --noEmit 2>&1
```

Expected: zero errors.

- [ ] **Step 4: Final commit if any loose changes remain**

```bash
git status
# If clean, nothing to do. If there are unstaged changes:
git add -p
git commit -m "chore(dashboard): final cleanup"
```
