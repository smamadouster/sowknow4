CREATE OR REPLACE PROCEDURE backfill_chunk_bucket_v2()
LANGUAGE plpgsql AS $$
DECLARE doc RECORD; i int := 0;
BEGIN
  FOR doc IN SELECT id, bucket::text AS b FROM sowknow.documents LOOP
    UPDATE sowknow.document_chunks SET bucket = doc.b
    WHERE document_id = doc.id AND bucket IS NULL;
    i := i + 1;
    IF i % 500 = 0 THEN
      RAISE NOTICE 'processed % documents', i;
      COMMIT;
    END IF;
  END LOOP;
  COMMIT;
END $$;

CALL backfill_chunk_bucket_v2();
DROP PROCEDURE backfill_chunk_bucket_v2();
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
