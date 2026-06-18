--liquibase formatted sql

--changeset srbs:003_usage_daily
CREATE TABLE IF NOT EXISTS usage_daily (
    user_id TEXT,
    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
    chat_requests INTEGER NOT NULL DEFAULT 0,
    embedding_calls INTEGER NOT NULL DEFAULT 0,
    upload_bytes BIGINT NOT NULL DEFAULT 0,
    api_token_calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, usage_date)
);

CREATE INDEX IF NOT EXISTS usage_daily_date_idx ON usage_daily (usage_date DESC);

--changeset srbs:003_user_quotas
CREATE TABLE IF NOT EXISTS user_quotas (
    user_id TEXT PRIMARY KEY,
    max_chat_per_day INTEGER NOT NULL DEFAULT 100,
    max_storage_mb INTEGER NOT NULL DEFAULT 500,
    max_documents INTEGER NOT NULL DEFAULT 50,
    max_concurrent_jobs INTEGER NOT NULL DEFAULT 2,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
