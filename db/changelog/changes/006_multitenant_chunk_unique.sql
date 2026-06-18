--liquibase formatted sql

--changeset srbs:006_rag_chunks_unique_per_user
DROP INDEX IF EXISTS rag_chunks_doc_hash_chunk_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS rag_chunks_user_doc_hash_chunk_uniq
    ON rag_chunks (user_id, document_id, content_hash, chunk_index);
