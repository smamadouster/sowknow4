#!/usr/bin/env python3
"""Quick diagnostic for stuck PNG/JPEG files."""
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from sqlalchemy import func, text

db = SessionLocal()
try:
    print("=== Image files in bad states ===")
    rows = db.execute(text("""
        SELECT id, filename, original_filename, status, pipeline_stage,
               pipeline_error, pipeline_retry_count, created_at
        FROM sowknow.documents
        WHERE filename ~* '\.(png|jpe?g)$'
          AND status IN ('pending', 'processing', 'error')
        ORDER BY created_at DESC
        LIMIT 20
    """))
    for r in rows.mappings():
        print(dict(r))

    print("\n=== Image pipeline stages FAILED or RUNNING ===")
    rows = db.execute(text("""
        SELECT ps.stage, ps.status, ps.attempt, ps.error_message,
               d.filename, d.id::text as doc_id
        FROM sowknow.pipeline_stages ps
        JOIN sowknow.documents d ON d.id = ps.document_id
        WHERE d.filename ~* '\.(png|jpe?g)$'
          AND ps.status IN ('failed', 'running')
        ORDER BY ps.stage, ps.status
        LIMIT 30
    """))
    for r in rows.mappings():
        print(dict(r))

    print("\n=== Document status breakdown (images only) ===")
    rows = db.execute(text("""
        SELECT status, COUNT(*) as cnt
        FROM sowknow.documents
        WHERE filename ~* '\.(png|jpe?g)$'
        GROUP BY status
        ORDER BY cnt DESC
    """))
    for r in rows.mappings():
        print(f"  {r['status']:15} {r['cnt']:>6}")

    print("\n=== CHUNKED stage failures by error pattern ===")
    rows = db.execute(text("""
        SELECT ps.error_message, COUNT(*) as cnt
        FROM sowknow.pipeline_stages ps
        JOIN sowknow.documents d ON d.id = ps.document_id
        WHERE d.filename ~* '\.(png|jpe?g)$'
          AND ps.stage = 'chunked'
          AND ps.status = 'failed'
        GROUP BY ps.error_message
        ORDER BY cnt DESC
    """))
    for r in rows.mappings():
        print(f"  ({r['cnt']}) {r['error_message']}")

    print("\n=== OCR stage failures by error pattern ===")
    rows = db.execute(text("""
        SELECT ps.error_message, COUNT(*) as cnt
        FROM sowknow.pipeline_stages ps
        JOIN sowknow.documents d ON d.id = ps.document_id
        WHERE d.filename ~* '\.(png|jpe?g)$'
          AND ps.stage = 'ocr'
          AND ps.status = 'failed'
        GROUP BY ps.error_message
        ORDER BY cnt DESC
    """))
    for r in rows.mappings():
        print(f"  ({r['cnt']}) {r['error_message']}")

finally:
    db.close()
