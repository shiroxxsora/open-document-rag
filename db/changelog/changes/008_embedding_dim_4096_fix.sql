--liquibase formatted sql

--changeset srbs:008_embedding_dim_4096_fix
--preconditions onFail:MARK_RAN
--precondition-sql-check expectedResult:2048 SELECT COALESCE((SELECT a.atttypmod FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid JOIN pg_namespace n ON c.relnamespace = n.oid WHERE c.relname = 'rag_chunks' AND a.attname = 'embedding' AND n.nspname = 'public' LIMIT 1), 0)
DROP INDEX IF EXISTS rag_chunks_embedding_idx;
TRUNCATE TABLE rag_chunks;
ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE vector(4096);
UPDATE rag_documents
SET status = 'pending', content_hash = NULL, error = NULL, updated_at = now();
