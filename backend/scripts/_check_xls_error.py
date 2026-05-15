#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT id::text as doc_id, filename, original_filename, status, pipeline_stage,
               pipeline_error, pipeline_retry_count, file_path, mime_type, chunk_count,
               metadata, created_at, updated_at
        FROM sowknow.documents
        WHERE original_filename ILIKE '%PAIE AUG13%'
           OR filename ILIKE '%PAIE AUG13%'
        ORDER BY updated_at DESC
        LIMIT 5
    """))
    docs = list(rows.mappings())
    if not docs:
        print("No matching document found")
    else:
        for d in docs:
            print("=== Document ===")
            for k, v in dict(d).items():
                print(f"  {k}: {v}")
            print()

            ps_rows = db.execute(text("""
                SELECT stage, status, attempt, error_message, started_at, completed_at
                FROM sowknow.pipeline_stages
                WHERE document_id = :doc_id
                ORDER BY stage
            """), {"doc_id": d["doc_id"]})
            print("  Pipeline stages:")
            for ps in ps_rows.mappings():
                print(f"    {ps['stage']:12} | {ps['status']:12} | attempt={ps['attempt']} | error={ps['error_message']}")
            print()

            import os
            txt_path = d["file_path"] + ".txt" if d["file_path"] else None
            if txt_path:
                if os.path.exists(txt_path):
                    size = os.path.getsize(txt_path)
                    print(f"  .txt sidecar: EXISTS ({size} bytes)")
                    if size > 0 and size < 2000:
                        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                            preview = f.read(500)
                        print(f"  Preview: {preview[:500]!r}")
                else:
                    print(f"  .txt sidecar: MISSING ({txt_path})")
            print()

finally:
    db.close()
