# Dashboard Live Pipeline Monitoring — Design Spec
**Date:** 2026-04-12  
**Status:** Approved

## Problem

The admin dashboard at `/dashboard` has multiple concrete bugs that make it show zeros and empty tables despite real data existing in the database. Additionally, it lacks visibility into per-stage pipeline progress, which is critical when monitoring a large batch of documents (e.g. 2500 docs stuck slowly working through embedding).

### Bugs Identified

| Bug | Root Cause |
|-----|-----------|
| Queue stats always show 0 | Frontend reads `pending/in_progress/failed`; backend sends `pending_tasks/in_progress_tasks/failed_tasks` |
| `indexed_pages` always 0 | Frontend reads `indexed_pages`; backend sends `indexed_documents` |
| `active_users_today` always 0 | Frontend reads `active_users_today`; backend sends `active_sessions` |
| Anomaly table always empty | Frontend reads `hours_stuck`; backend sends `stuck_duration_hours` |
| Fake uploads chart | Lines 82–88 in `page.tsx` generate random variance around `uploads_today` — no real DB query |
| No pipeline stage breakdown | `/queue-stats` returns only total counts, not per-stage funnel or throughput |
| 60s refresh | Too slow for live pipeline monitoring |

---

## Solution Overview

**Option A: Fix bugs + fast polling + pipeline panel.**  
No SSE, no Redis counters. Fix frontend field names, add two new backend endpoints, add a pipeline funnel panel, use two independent polling intervals.

---

## Section 1 — Bug Fixes (Frontend Only)

**File:** `frontend/app/[locale]/dashboard/page.tsx`

Update TypeScript interfaces and all read sites:

```typescript
// QueueStats interface
interface QueueStats {
  pending_tasks: number;
  in_progress_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  average_wait_time: number | null;
  longest_running_task: string | null;
}

// Stats interface (match backend SystemStats)
interface Stats {
  total_documents: number;
  uploads_today: number;
  indexed_documents: number;   // was indexed_pages
  public_documents: number;
  confidential_documents: number;
  total_users: number;
  active_sessions: number;     // was active_users_today
  processing_documents: number;
  error_documents: number;
}

// Anomaly interface
interface Anomaly {
  document_id: string;
  filename: string;
  bucket: string;
  status: string;
  error_message: string | null;
  stuck_duration_hours: number;  // was hours_stuck
  created_at: string;
  last_task_type: string | null;
}
```

All render sites updated accordingly. `total` for the queue card computed client-side:  
`pending_tasks + in_progress_tasks + failed_tasks`

Anomaly table key: changed from `anomaly.id` (doesn't exist in backend) to `anomaly.document_id`.

---

## Section 2 — New Backend Endpoints

**File:** `backend/app/api/admin.py`

### `GET /admin/pipeline-stats`

Runs two efficient queries on `processing_queue` (both use indexed columns):

**Query 1 — Stage funnel** (active tasks only):
```sql
SELECT task_type, status, COUNT(*)
FROM processing_queue
WHERE status IN ('pending', 'in_progress', 'failed')
GROUP BY task_type, status
```

**Query 2 — Throughput** (two windows):
```sql
-- Per-hour rate
SELECT task_type, COUNT(*) as rate
FROM processing_queue
WHERE status = 'completed' AND completed_at >= NOW() - INTERVAL '1 hour'
GROUP BY task_type

-- Per-10-minute rate
SELECT task_type, COUNT(*) as rate
FROM processing_queue
WHERE status = 'completed' AND completed_at >= NOW() - INTERVAL '10 minutes'
GROUP BY task_type
```

**Response schema:**
```json
{
  "stages": [
    {
      "stage": "ocr_processing",
      "pending": 0,
      "in_progress": 2,
      "failed": 1,
      "throughput_per_hour": 45,
      "throughput_per_10min": 8
    },
    {
      "stage": "embedding_generation",
      "pending": 2200,
      "in_progress": 5,
      "failed": 0,
      "throughput_per_hour": 12,
      "throughput_per_10min": 2
    }
  ],
  "total_active": 7,
  "bottleneck_stage": "embedding_generation"
}
```

`bottleneck_stage` = stage with highest `pending` count. Stages with zero activity across all statuses are omitted from the response. All 5 stages are always present in the response (with zeros) to keep the frontend funnel stable.

Stage order (always rendered in this order):
1. `ocr_processing`
2. `text_extraction`
3. `chunking`
4. `embedding_generation`
5. `indexing`

### `GET /admin/uploads-history`

```sql
SELECT DATE(created_at AT TIME ZONE 'UTC') as day, COUNT(*) as count
FROM sowknow.documents
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY day
ORDER BY day ASC
```

Response: `{ "history": [{"day": "2026-04-06", "count": 12}, ...] }`  
Frontend fills missing days with 0.

---

## Section 3 — Frontend: Pipeline Panel + Real Uploads Chart

### PipelinePanel Component

New section added to `page.tsx` between the charts row and the anomalies table.

**Layout:**
- Header: "Pipeline" + "Total active: N" badge + last-refreshed timestamp
- 5 rows (one per stage), always in fixed order
- Bottleneck stage row highlighted with amber left border
- Each row:
  - Stage label (human-readable: "OCR", "Text Extraction", "Chunking", "Embedding", "Indexing")
  - Pending count (large, yellow)
  - In-progress count (blue)
  - Failed badge (red, hidden if 0)
  - Throughput: `12/hr · 2/10min`
  - Horizontal bar showing relative pending volume (max-width scaled to largest pending count)

### Real Uploads Chart

Remove lines 82–88 (fake data generation). Fetch from `GET /admin/uploads-history`. Fill missing days with 0. The existing AreaChart component is reused.

### Polling Structure

Two independent `setInterval` timers:

| Data | Interval | Endpoints |
|------|----------|-----------|
| Pipeline stats + queue stats | **10 seconds** | `/admin/pipeline-stats`, `/admin/queue-stats` |
| Stats cards + uploads history | **60 seconds** | `/admin/stats`, `/admin/uploads-history` |

Anomalies remain on the 60s cycle (they don't change fast).

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/app/[locale]/dashboard/page.tsx` | Fix interfaces, fix field reads, add PipelinePanel, two polling intervals, real uploads data |
| `backend/app/api/admin.py` | Add `GET /admin/pipeline-stats` and `GET /admin/uploads-history` |
| `backend/app/schemas/admin.py` | Add `PipelineStageStats`, `PipelineStatsResponse`, `UploadsHistoryResponse` schemas |

No migrations required. No new models. No worker changes.

---

## Non-Goals

- SSE / WebSocket real-time streaming
- Redis-backed counters
- Per-document progress tracking
- Mobile layout changes to the dashboard
