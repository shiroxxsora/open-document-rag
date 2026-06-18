--liquibase formatted sql

--changeset srbs:002_job_queue
CREATE TABLE IF NOT EXISTS job_queue (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT,
    job_type TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CONSTRAINT job_queue_status_check CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS job_queue_claim_idx
    ON job_queue (status, next_run_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS job_queue_user_id_idx ON job_queue (user_id);

CREATE TABLE IF NOT EXISTS job_dead_letter (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL,
    user_id TEXT,
    job_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    attempts INTEGER NOT NULL,
    last_error TEXT,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS job_dead_letter_failed_at_idx ON job_dead_letter (failed_at DESC);

CREATE TABLE IF NOT EXISTS worker_heartbeat (
    worker_id TEXT PRIMARY KEY,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
