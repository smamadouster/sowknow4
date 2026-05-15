#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT id::text as doc_id, original_filename, status, pipeline_stage, pipeline_error, chunk_count
        FROM sowknow.documents
        WHERE id = '47cbb5ad-3c7c-4e13-99f4-f76d166c22a7'
    """))
    for r in rows.mappings():
        print(f"{r['original_filename']:20} | {r['status']:12} | {r['pipeline_stage']:12} | chunks={r['chunk_count']} | err={r['pipeline_error'] or ''}")

    print("\nPipeline stages:")
    rows = db.execute(text("""
        SELECT stage, status, attempt, error_message
        FROM sowknow.pipeline_stages
        WHERE document_id = '47cbb5ad-3c7c-4e13-99f4-f76d166c22a7'
        ORDER BY stage
    """))
    for r in rows.mappings():
        print(f"  {r['stage']:12} | {r['status']:12} | attempt={r['attempt']} | err={r['error_message'] or ''}")
finally:
    db.close()
