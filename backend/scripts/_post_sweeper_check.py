#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print("=== Images currently pending/processing/error after sweeper ===")
    rows = db.execute(text("""
        SELECT status, pipeline_stage, COUNT(*) as cnt
        FROM sowknow.documents
        WHERE filename ~* '\.(png|jpe?g)$'
        GROUP BY status, pipeline_stage
        ORDER BY status, pipeline_stage
    """))
    for r in rows.mappings():
        print(f"  {r['status']:12} {r['pipeline_stage']:12} {r['cnt']:>4}")

    print("\n=== All document types: pending/running/failed pipeline stages ===")
    rows = db.execute(text("""
        SELECT ps.stage, ps.status, COUNT(*) as cnt
        FROM sowknow.pipeline_stages ps
        JOIN sowknow.documents d ON d.id = ps.document_id
        GROUP BY ps.stage, ps.status
        ORDER BY ps.stage, ps.status
    """))
    for r in rows.mappings():
        if r['status'] in ('pending', 'running', 'failed'):
            print(f"  {r['stage']:12} {r['status']:12} {r['cnt']:>4}")

    print("\n=== Specific image files still in error ===")
    rows = db.execute(text("""
        SELECT id::text as doc_id, filename, original_filename, status, pipeline_stage, pipeline_error
        FROM sowknow.documents
        WHERE filename ~* '\.(png|jpe?g)$'
          AND status = 'error'
        ORDER BY created_at DESC
    """))
    for r in rows.mappings():
        print(f"  {r['doc_id']} | {r['original_filename']:30} | {r['pipeline_error']}")

finally:
    db.close()
