#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    rows = db.execute(text("""
        SELECT id::text as doc_id, original_filename, status, pipeline_stage, pipeline_error
        FROM sowknow.documents
        WHERE id IN (
            '3acce116-d78f-4444-8400-7f013d6acbbe',
            'e0fcc02d-ca24-40d9-90b9-23e1b5fb6c40',
            'adf95665-5820-447d-9ab8-03e1ed158ccc',
            '5991202c-8cbf-4eaf-8d41-c29c6cd02b82'
        )
        ORDER BY original_filename
    """))
    for r in rows.mappings():
        err = r['pipeline_error'] or ""
        print(f"{r['original_filename']:20} | {r['status']:12} | {r['pipeline_stage']:12} | {err}")
finally:
    db.close()
