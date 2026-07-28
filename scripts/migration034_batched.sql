-- Fallback for migration 034 if the monolithic backfill UPDATE must be killed:
-- batched, resumable version (10k rows/transaction, no giant WAL burst).
-- Run: psql -f scripts/migration034_batched.sql  (inside sowknow-postgres)
-- Safe to re-run: idempotent (column/index/triggers IF NOT EXISTS/CREATE OR REPLACE).

ALTER TABLE sowknow.document_chunks ADD COLUMN IF NOT EXISTS bucket varchar(20);

-- Batched backfill loop (psql \watch is not transactional; use a DO block with
-- per-iteration commits via a procedure)
CREATE OR REPLACE PROCEDURE backfill_chunk_bucket(batch int DEFAULT 10000)
LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  LOOP
    UPDATE sowknow.document_chunks dc
    SET bucket = d.bucket::text
    FROM sowknow.documents d
    WHERE dc.document_id = d.id
      AND dc.id IN (SELECT id FROM sowknow.document_chunks WHERE bucket IS NULL LIMIT batch);
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'backfilled % rows', n;
    COMMIT;
    EXIT WHEN n = 0;
  END LOOP;
END $$;

CALL backfill_chunk_bucket(10000);
DROP PROCEDURE backfill_chunk_bucket(int);

ALTER TABLE sowknow.document_chunks ALTER COLUMN bucket SET NOT NULL;
ALTER TABLE sowknow.document_chunks ALTER COLUMN bucket SET DEFAULT 'public';

-- CONCURRENTLY outside transaction block (run as separate psql -c if needed)
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_document_chunks_bucket
  ON sowknow.document_chunks (bucket);

CREATE OR REPLACE FUNCTION sowknow_set_chunk_bucket() RETURNS trigger AS $$
BEGIN
    SELECT bucket::text INTO NEW.bucket FROM sowknow.documents WHERE id = NEW.document_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS chunk_bucket_sync ON sowknow.document_chunks;
CREATE TRIGGER chunk_bucket_sync
BEFORE INSERT OR UPDATE OF document_id ON sowknow.document_chunks
FOR EACH ROW EXECUTE FUNCTION sowknow_set_chunk_bucket();

CREATE OR REPLACE FUNCTION sowknow_propagate_doc_bucket() RETURNS trigger AS $$
BEGIN
    IF NEW.bucket IS DISTINCT FROM OLD.bucket THEN
        UPDATE sowknow.document_chunks SET bucket = NEW.bucket::text
        WHERE document_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS document_bucket_propagate ON sowknow.documents;
CREATE TRIGGER document_bucket_propagate
AFTER UPDATE OF bucket ON sowknow.documents
FOR EACH ROW EXECUTE FUNCTION sowknow_propagate_doc_bucket();

-- Stamp alembic so 034 is not re-run
UPDATE alembic_version SET version_num = '034_chunk_bucket_denorm';
