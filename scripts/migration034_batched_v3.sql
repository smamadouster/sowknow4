-- v3: chunk-id-ordered batches — steady progress even with 72k-chunk outlier docs.
CREATE OR REPLACE PROCEDURE backfill_chunk_bucket_v3()
LANGUAGE plpgsql AS $$
DECLARE n int; total int := 0;
BEGIN
  LOOP
    WITH batch AS (
      SELECT id FROM sowknow.document_chunks
      WHERE bucket IS NULL ORDER BY id LIMIT 10000
    )
    UPDATE sowknow.document_chunks dc
    SET bucket = d.bucket::text
    FROM sowknow.documents d
    WHERE dc.document_id = d.id
      AND dc.id IN (SELECT id FROM batch);
    GET DIAGNOSTICS n = ROW_COUNT;
    total := total + n;
    RAISE NOTICE 'batch % rows, total %', n, total;
    COMMIT;
    EXIT WHEN n = 0;
  END LOOP;
END $$;

CALL backfill_chunk_bucket_v3();
DROP PROCEDURE backfill_chunk_bucket_v3();
DROP PROCEDURE IF EXISTS backfill_chunk_bucket_v2();
DROP PROCEDURE IF EXISTS backfill_chunk_bucket(int);

ALTER TABLE sowknow.document_chunks ALTER COLUMN bucket SET NOT NULL;
ALTER TABLE sowknow.document_chunks ALTER COLUMN bucket SET DEFAULT 'public';

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

UPDATE alembic_version SET version_num = '034_chunk_bucket_denorm';
