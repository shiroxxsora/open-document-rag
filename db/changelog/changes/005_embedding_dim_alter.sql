--liquibase formatted sql

--changeset srbs:005_embedding_dim_alter
--preconditions onFail:MARK_RAN
--precondition-sql-check expectedResult:0 SELECT COALESCE((SELECT (a.atttypmod - 4) / 2 FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid JOIN pg_namespace n ON c.relnamespace = n.oid WHERE c.relname = 'rag_chunks' AND a.attname = 'embedding' AND n.nspname = 'public' LIMIT 1), 0)
DROP INDEX IF EXISTS rag_chunks_embedding_idx;
TRUNCATE TABLE rag_chunks;
ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE vector(2048);
UPDATE rag_documents
SET status = 'pending', content_hash = NULL, error = NULL, updated_at = now();

--changeset srbs:005_embedding_ivfflat_recreate runOnChange:true
--preconditions onFail:MARK_RAN
--precondition-sql-check expectedResult:1 SELECT CASE WHEN 2048 <= 2000 THEN 1 ELSE 0 END
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
