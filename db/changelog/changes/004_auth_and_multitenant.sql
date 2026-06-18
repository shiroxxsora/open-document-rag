--liquibase formatted sql

--changeset srbs:004_schema_migrations_meta
CREATE TABLE IF NOT EXISTS schema_migrations_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

--changeset srbs:004_users
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    provider TEXT NOT NULL,
    provider_sub TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT users_provider_sub_uniq UNIQUE (provider, provider_sub)
);

CREATE INDEX IF NOT EXISTS users_email_idx ON users (email);

--changeset srbs:004_user_settings
CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    llm_api_url TEXT,
    llm_model TEXT,
    llm_api_key_encrypted TEXT,
    embedding_api_url TEXT,
    embedding_model TEXT,
    embedding_api_key_encrypted TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

--changeset srbs:004_chat_sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_sessions_user_id_idx ON chat_sessions (user_id, updated_at DESC);

--changeset srbs:004_chat_messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_messages_role_check CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX IF NOT EXISTS chat_messages_session_id_idx ON chat_messages (session_id, id ASC);

--changeset srbs:004_api_applications
CREATE TABLE IF NOT EXISTS api_applications (
    app_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    webhook_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS api_applications_user_id_idx ON api_applications (user_id);

--changeset srbs:004_api_tokens
CREATE TABLE IF NOT EXISTS api_tokens (
    token_id TEXT PRIMARY KEY,
    app_id TEXT NOT NULL REFERENCES api_applications(app_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token_prefix TEXT NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    label TEXT,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS api_tokens_user_id_idx ON api_tokens (user_id);
CREATE INDEX IF NOT EXISTS api_tokens_app_id_idx ON api_tokens (app_id);

--changeset srbs:004_rag_documents_user_id_add
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS user_id TEXT;

--changeset srbs:004_system_user
INSERT INTO users (user_id, email, display_name, provider, provider_sub)
VALUES ('system', 'system@localhost', 'System', 'system', 'system')
ON CONFLICT (user_id) DO NOTHING;

--changeset srbs:004_rag_documents_backfill
UPDATE rag_documents SET user_id = 'system' WHERE user_id IS NULL;

--changeset srbs:004_rag_documents_user_id_not_null
ALTER TABLE rag_documents ALTER COLUMN user_id SET NOT NULL;

--changeset srbs:004_rag_documents_user_fk
ALTER TABLE rag_documents
    ADD CONSTRAINT rag_documents_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;

--changeset srbs:004_rag_chunks_user_id_add
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS user_id TEXT;

--changeset srbs:004_rag_chunks_backfill
UPDATE rag_chunks c
SET user_id = d.user_id
FROM rag_documents d
WHERE c.document_id = d.document_id AND c.user_id IS NULL;

--changeset srbs:004_rag_chunks_user_id_not_null
ALTER TABLE rag_chunks ALTER COLUMN user_id SET NOT NULL;

--changeset srbs:004_rag_documents_composite_pk
ALTER TABLE rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_document_id_fkey;
ALTER TABLE rag_documents DROP CONSTRAINT rag_documents_pkey;
ALTER TABLE rag_documents ADD PRIMARY KEY (user_id, document_id);

--changeset srbs:004_rag_chunks_user_fk
ALTER TABLE rag_chunks
    ADD CONSTRAINT rag_chunks_document_fkey
    FOREIGN KEY (user_id, document_id) REFERENCES rag_documents(user_id, document_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS rag_documents_user_id_idx ON rag_documents (user_id);
CREATE INDEX IF NOT EXISTS rag_chunks_user_id_idx ON rag_chunks (user_id);

--changeset srbs:004_usage_backfill
UPDATE usage_daily SET user_id = 'system' WHERE user_id IS NULL OR user_id = '';
UPDATE user_quotas SET user_id = 'system' WHERE user_id IS NULL OR user_id = '';

--changeset srbs:004_schema_meta
INSERT INTO schema_migrations_meta (key, value)
VALUES ('auth_phase', 'complete')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
