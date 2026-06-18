from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request
from psycopg import connect

from app.config import Settings
from app.schemas import UsageHistoryResponse, UsageLimits, UsageResponse, UsageSnapshot

logger = logging.getLogger(__name__)

GLOBAL_USER_KEY = ""


@dataclass(frozen=True)
class QuotaLimits:
    max_chat_per_day: int
    max_storage_mb: int
    max_documents: int
    max_concurrent_jobs: int


class UsageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _defaults(self) -> QuotaLimits:
        return QuotaLimits(
            max_chat_per_day=self.settings.default_max_chat_per_day,
            max_storage_mb=self.settings.default_max_storage_mb,
            max_documents=self.settings.default_max_documents,
            max_concurrent_jobs=self.settings.default_max_concurrent_jobs,
        )

    def get_limits(self, user_id: str | None = None) -> QuotaLimits:
        key = user_id if user_id else GLOBAL_USER_KEY
        defaults = self._defaults()
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT max_chat_per_day, max_storage_mb, max_documents, max_concurrent_jobs
                    FROM user_quotas
                    WHERE user_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return defaults
        return QuotaLimits(
            max_chat_per_day=int(row[0]),
            max_storage_mb=int(row[1]),
            max_documents=int(row[2]),
            max_concurrent_jobs=int(row[3]),
        )

    def get_today(self, user_id: str | None = None) -> UsageSnapshot:
        key = user_id if user_id else GLOBAL_USER_KEY
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chat_requests, embedding_calls, upload_bytes, api_token_calls
                    FROM usage_daily
                    WHERE user_id = %s AND usage_date = CURRENT_DATE
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return UsageSnapshot()
        return UsageSnapshot(
            chat_requests=int(row[0]),
            embedding_calls=int(row[1]),
            upload_bytes=int(row[2]),
            api_token_calls=int(row[3]),
        )

    def increment(
        self,
        user_id: str | None,
        *,
        chat_requests: int = 0,
        embedding_calls: int = 0,
        upload_bytes: int = 0,
        api_token_calls: int = 0,
    ) -> None:
        if not any((chat_requests, embedding_calls, upload_bytes, api_token_calls)):
            return
        key = user_id if user_id else GLOBAL_USER_KEY
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usage_daily (user_id, usage_date, chat_requests, embedding_calls, upload_bytes, api_token_calls)
                    VALUES (%s, CURRENT_DATE, %s, %s, %s, %s)
                    ON CONFLICT (user_id, usage_date) DO UPDATE SET
                        chat_requests = usage_daily.chat_requests + EXCLUDED.chat_requests,
                        embedding_calls = usage_daily.embedding_calls + EXCLUDED.embedding_calls,
                        upload_bytes = usage_daily.upload_bytes + EXCLUDED.upload_bytes,
                        api_token_calls = usage_daily.api_token_calls + EXCLUDED.api_token_calls
                    """,
                    (
                        key,
                        chat_requests,
                        embedding_calls,
                        upload_bytes,
                        api_token_calls,
                    ),
                )

    def storage_used_mb(self, user_id: str | None = None) -> float:
        docs_dir = self.settings.docs_dir / user_id if user_id else self.settings.docs_dir
        if not docs_dir.exists():
            return 0.0
        total_bytes = sum(path.stat().st_size for path in docs_dir.rglob("*") if path.is_file())
        return total_bytes / (1024 * 1024)

    def document_count(self, user_id: str | None = None) -> int:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute("SELECT COUNT(*) FROM rag_documents WHERE user_id = %s", (user_id,))
                else:
                    cur.execute("SELECT COUNT(*) FROM rag_documents")
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def running_job_count(self, user_id: str | None = None) -> int:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM job_queue
                        WHERE user_id IS NOT DISTINCT FROM %s AND status IN ('pending', 'running')
                        """,
                        (user_id,),
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) FROM job_queue WHERE status IN ('pending', 'running')"
                    )
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def check_chat_quota(self, user_id: str | None = None) -> None:
        limits = self.get_limits(user_id)
        usage = self.get_today(user_id)
        if usage.chat_requests >= limits.max_chat_per_day:
            raise HTTPException(
                status_code=429,
                detail=f"Daily chat limit reached ({limits.max_chat_per_day}).",
                headers={"Retry-After": "86400"},
            )

    def check_upload_quota(
        self,
        user_id: str | None,
        upload_bytes: int,
        *,
        new_documents: int = 1,
    ) -> None:
        limits = self.get_limits(user_id)
        storage_mb = self.storage_used_mb(user_id) + upload_bytes / (1024 * 1024)
        if storage_mb > limits.max_storage_mb:
            raise HTTPException(
                status_code=429,
                detail=f"Storage limit exceeded ({limits.max_storage_mb} MB).",
            )
        doc_count = self.document_count(user_id) + new_documents
        if doc_count > limits.max_documents:
            raise HTTPException(
                status_code=429,
                detail=f"Document limit exceeded ({limits.max_documents}).",
            )
        if self.running_job_count(user_id) >= limits.max_concurrent_jobs:
            raise HTTPException(
                status_code=429,
                detail=f"Too many concurrent jobs (max {limits.max_concurrent_jobs}).",
            )

    def build_response(self, user_id: str | None = None) -> UsageResponse:
        limits = self.get_limits(user_id)
        usage = self.get_today(user_id)
        storage_mb = self.storage_used_mb(user_id)
        return UsageResponse(
            usage=usage,
            limits=UsageLimits(
                max_chat_per_day=limits.max_chat_per_day,
                max_storage_mb=limits.max_storage_mb,
                max_documents=limits.max_documents,
                max_concurrent_jobs=limits.max_concurrent_jobs,
            ),
            storage_used_mb=round(storage_mb, 2),
            document_count=self.document_count(user_id),
            running_jobs=self.running_job_count(user_id),
        )

    def history(self, user_id: str | None = None, days: int = 30) -> UsageHistoryResponse:
        from datetime import date, timedelta

        key = user_id if user_id else GLOBAL_USER_KEY
        since = date.today() - timedelta(days=max(1, days) - 1)
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT usage_date::text, chat_requests, embedding_calls, upload_bytes, api_token_calls
                    FROM usage_daily
                    WHERE user_id = %s AND usage_date >= %s
                    ORDER BY usage_date ASC
                    """,
                    (key, since),
                )
                rows = cur.fetchall()
        return UsageHistoryResponse(
            days=[
                UsageSnapshot(
                    date=str(row[0]),
                    chat_requests=int(row[1]),
                    embedding_calls=int(row[2]),
                    upload_bytes=int(row[3]),
                    api_token_calls=int(row[4]),
                )
                for row in rows
            ]
        )


def build_usage_router(usage_service: UsageService, get_user_id) -> APIRouter:
    router = APIRouter(prefix="/usage", tags=["usage"])

    @router.get("", response_model=UsageResponse)
    def get_usage(request: Request) -> UsageResponse:
        user_id = get_user_id(request)
        return usage_service.build_response(user_id)

    @router.get("/history", response_model=UsageHistoryResponse)
    def get_usage_history(request: Request) -> UsageHistoryResponse:
        user_id = get_user_id(request)
        return usage_service.history(user_id)

    return router
