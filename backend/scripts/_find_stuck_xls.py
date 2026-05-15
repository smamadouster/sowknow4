#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print("=== .xls / .xlt files in error or pending status ===")
    rows = db.execute(text("""
        SELECT id::text as doc_id, original_filename, filename, status, pipeline_stage,
               pipeline_error, created_at
        FROM sowknow.documents
        WHERE filename ~* '\.(xls|xlt)$'
          AND status IN ('error', 'pending', 'processing')
        ORDER BY status, created_at DESC
    """))
    docs = list(rows.mappings())
    for r in docs:
        print(f"  {r['status']:12} | {r['original_filename']:35} | stage={r['pipeline_stage']:12} | err={r['pipeline_error'] or ''}")
    print(f"\nTotal stuck .xls/.xlt files: {len(docs)}")

    print("\n=== .xls / .xlt files that are already indexed ===")
    rows = db.execute(text("""
        SELECT COUNT(*) as cnt
        FROM sowknow.documents
        WHERE filename ~* '\.(xls|xlt)$'
          AND status = 'indexed'
    """))
    for r in rows.mappings():
        print(f"  {r['cnt']} files successfully indexed")

finally:
    db.close()
