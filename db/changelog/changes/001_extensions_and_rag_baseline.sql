--liquibase formatted sql

--changeset srbs:001_extensions_and_rag_baseline
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    document_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rag_documents(document_id) ON DELETE CASCADE,
    document_name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    source_page TEXT,
    embedding vector(${embedding.dim}) NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS rag_chunks_doc_hash_chunk_uniq
    ON rag_chunks (document_id, content_hash, chunk_index);

CREATE INDEX IF NOT EXISTS rag_chunks_document_id_idx ON rag_chunks (document_id);

--changeset srbs:001_rag_embedding_ivfflat runOnChange:true
--preconditions onFail:MARK_RAN
--precondition-sql-check expectedResult:1 SELECT CASE WHEN ${embedding.dim} <= 2000 THEN 1 ELSE 0 END
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
