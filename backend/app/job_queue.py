from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import connect
from psycopg.types.json import Jsonb

from app.config import Settings
from app.text_sanitize import sanitize_pg_text

logger = logging.getLogger(__name__)

TRANSIENT_HTTP_CODES = {429, 502, 503, 504}
PERMANENT_HTTP_CODES = {401, 403}
RETRY_BACKOFF_SECONDS = (30, 120, 600, 1800)
CANCELLED_MESSAGE = "Cancelled by user."


@dataclass(frozen=True)
class Job:
    id: int
    user_id: str | None
    job_type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    next_run_at: datetime
    last_error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _row_to_job(row: tuple[Any, ...]) -> Job:
    payload = row[3]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Job(
        id=int(row[0]),
        user_id=row[1],
        job_type=str(row[2]),
        payload=dict(payload or {}),
        status=str(row[4]),
        attempts=int(row[5]),
        max_attempts=int(row[6]),
        next_run_at=row[7],
        last_error=str(row[8]) if row[8] is not None else None,
        created_at=row[9],
        started_at=row[10],
        finished_at=row[11],
    )


def classify_error(error: Exception | str) -> tuple[bool, str]:
    message = str(error)
    upper = message.upper()
    for code in PERMANENT_HTTP_CODES:
        if f"HTTP {code}" in upper or f" {code} " in f" {upper} ":
            return False, message
    for code in TRANSIENT_HTTP_CODES:
        if f"HTTP {code}" in upper:
            return True, message
    if "timeout" in message.lower() or "timed out" in message.lower():
        return True, message
    if "parse" in message.lower() or "unsupported" in message.lower():
        return False, message
    return True, message


def retry_delay_seconds(attempts: int) -> int:
    index = min(max(attempts - 1, 0), len(RETRY_BACKOFF_SECONDS) - 1)
    return RETRY_BACKOFF_SECONDS[index]


class JobQueue:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        *,
        user_id: str | None = None,
        max_attempts: int | None = None,
    ) -> int:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO job_queue (user_id, job_type, payload_json, max_attempts)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        user_id,
                        job_type,
                        Jsonb(payload or {}),
                        max_attempts or self.settings.job_max_attempts,
                    ),
                )
                row = cur.fetchone()
        job_id = int(row[0])
        logger.info("Enqueued job %s type=%s user_id=%s", job_id, job_type, user_id)
        return job_id

    def claim(self, worker_id: str | None = None) -> Job | None:
        with connect(self.settings.postgres_dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, job_type, payload_json, status, attempts, max_attempts,
                           next_run_at, last_error, created_at, started_at, finished_at
                    FROM job_queue
                    WHERE status = 'pending' AND next_run_at <= now()
                    ORDER BY next_run_at ASC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row is None:
                    conn.commit()
                    return None
                job_id = int(row[0])
                cur.execute(
                    """
                    UPDATE job_queue
                    SET status = 'running', started_at = now(), attempts = attempts + 1
                    WHERE id = %s
                    RETURNING id, user_id, job_type, payload_json, status, attempts, max_attempts,
                              next_run_at, last_error, created_at, started_at, finished_at
                    """,
                    (job_id,),
                )
                updated = cur.fetchone()
                if worker_id:
                    cur.execute(
                        """
                        INSERT INTO worker_heartbeat (worker_id, last_seen_at)
                        VALUES (%s, now())
                        ON CONFLICT (worker_id) DO UPDATE SET last_seen_at = now()
                        """,
                        (worker_id,),
                    )
            conn.commit()
        return _row_to_job(updated) if updated else None

    def is_job_running(self, job_id: int) -> bool:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM job_queue WHERE id = %s", (job_id,))
                row = cur.fetchone()
        return row is not None and str(row[0]) == "running"

    def complete(self, job_id: int) -> None:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE job_queue
                    SET status = 'completed', finished_at = now(), last_error = NULL
                    WHERE id = %s AND status = 'running'
                    """,
                    (job_id,),
                )

    def cancel_indexing_jobs(
        self,
        user_id: str,
        *,
        document_id: str | None = None,
        include_full_reindex: bool = True,
    ) -> int:
        job_types = ["index_document"]
        if include_full_reindex and document_id is None:
            job_types.append("full_reindex")
        clauses = [
            "user_id = %s",
            "status IN ('pending', 'running')",
            "job_type = ANY(%s)",
        ]
        params: list[Any] = [CANCELLED_MESSAGE, user_id, job_types]
        if document_id is not None:
            clauses.append("job_type = 'index_document'")
            clauses.append("payload_json->>'document_id' = %s")
            params.append(document_id)
        where_sql = " AND ".join(clauses)
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE job_queue
                    SET status = 'failed',
                        finished_at = now(),
                        last_error = %s,
                        started_at = NULL
                    WHERE {where_sql}
                    RETURNING id
                    """,
                    params,
                )
                rows = cur.fetchall()
        cancelled = len(rows)
        if cancelled:
            logger.info(
                "Cancelled %s indexing job(s) for user_id=%s document_id=%s",
                cancelled,
                user_id,
                document_id,
            )
        return cancelled

    def fail(self, job: Job, error: Exception | str, *, permanent: bool | None = None) -> None:
        retryable, message = classify_error(error)
        if permanent is not None:
            retryable = not permanent
        truncated = sanitize_pg_text(message[:2000]) or "Unknown error"
        if retryable and job.attempts < job.max_attempts:
            delay = retry_delay_seconds(job.attempts)
            next_run = datetime.now(timezone.utc) + timedelta(seconds=delay)
            with connect(self.settings.postgres_dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE job_queue
                        SET status = 'pending',
                            next_run_at = %s,
                            last_error = %s,
                            started_at = NULL
                        WHERE id = %s
                        """,
                        (next_run, truncated, job.id),
                    )
            logger.warning(
                "Job %s failed (attempt %s/%s), retry in %ss: %s",
                job.id,
                job.attempts,
                job.max_attempts,
                delay,
                truncated,
            )
            return
        self._move_to_dlq(job, truncated)

    def _move_to_dlq(self, job: Job, message: str) -> None:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO job_dead_letter (job_id, user_id, job_type, payload_json, attempts, last_error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (job.id, job.user_id, job.job_type, Jsonb(job.payload), job.attempts, message),
                )
                cur.execute(
                    """
                    UPDATE job_queue
                    SET status = 'failed', finished_at = now(), last_error = %s
                    WHERE id = %s
                    """,
                    (message, job.id),
                )
        logger.error("Job %s moved to DLQ after %s attempts: %s", job.id, job.attempts, message)

    def count_by_status(self, statuses: list[str], *, user_id: str | None = None) -> int:
        if not statuses:
            return 0
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute(
                        "SELECT COUNT(*) FROM job_queue WHERE status = ANY(%s) AND user_id = %s",
                        (statuses, user_id),
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) FROM job_queue WHERE status = ANY(%s)",
                        (statuses,),
                    )
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def requeue_stale_running_jobs(self, older_than_sec: int) -> int:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE job_queue
                    SET status = 'pending',
                        next_run_at = now(),
                        started_at = NULL,
                        last_error = COALESCE(last_error, '') || ' [requeued stale running job]'
                    WHERE status = 'running'
                      AND started_at IS NOT NULL
                      AND started_at < now() - make_interval(secs => %s)
                    RETURNING id
                    """,
                    (older_than_sec,),
                )
                rows = cur.fetchall()
        if rows:
            logger.warning("Requeued %s stale running job(s)", len(rows))
        return len(rows)

    def count_dlq(self) -> int:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM job_dead_letter")
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def count_stuck_jobs(self, older_than_sec: int) -> int:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM job_queue
                    WHERE status = 'running'
                      AND started_at IS NOT NULL
                      AND started_at < now() - make_interval(secs => %s)
                    """,
                    (older_than_sec,),
                )
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def worker_last_seen(self, worker_id: str | None = None) -> datetime | None:
        target = worker_id or self.settings.job_worker_id
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_seen_at FROM worker_heartbeat WHERE worker_id = %s",
                    (target,),
                )
                row = cur.fetchone()
        return row[0] if row else None

    def touch_worker_heartbeat(self, worker_id: str | None = None) -> None:
        target = worker_id or self.settings.job_worker_id
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO worker_heartbeat (worker_id, last_seen_at)
                    VALUES (%s, now())
                    ON CONFLICT (worker_id) DO UPDATE SET last_seen_at = now()
                    """,
                    (target,),
                )
