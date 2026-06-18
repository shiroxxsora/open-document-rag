from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from psycopg import connect

from app.config import Settings
from app.job_queue import JobQueue
from app.llm_client import LLMClient
from app.repository import RAGRepository
from app.schemas import HealthComponent, HealthResponse

logger = logging.getLogger(__name__)

REQUIRED_TABLES = (
    "rag_documents",
    "rag_chunks",
    "job_queue",
    "job_dead_letter",
    "usage_daily",
    "user_quotas",
    "users",
    "user_settings",
    "chat_sessions",
    "chat_messages",
    "api_applications",
    "api_tokens",
)


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: str
    latency_ms: int
    message: str | None = None


class HealthChecker:
    def __init__(self, settings: Settings, repo: RAGRepository, queue: JobQueue) -> None:
        self.settings = settings
        self.repo = repo
        self.queue = queue
        self.llm = LLMClient.from_settings(settings)

    def probe_postgres(self) -> ProbeResult:
        start = time.perf_counter()
        try:
            with connect(self.settings.postgres_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    if cur.fetchone() is None:
                        raise RuntimeError("pgvector extension missing")
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("postgres", "ok", latency)
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("postgres", "down", latency, str(exc))

    def probe_migrations(self) -> ProbeResult:
        start = time.perf_counter()
        try:
            with connect(self.settings.postgres_dsn) as conn:
                with conn.cursor() as cur:
                    for table in REQUIRED_TABLES:
                        cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                        row = cur.fetchone()
                        if row is None or row[0] is None:
                            raise RuntimeError(f"Missing table: {table}")
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("migrations", "ok", latency)
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("migrations", "down", latency, str(exc))

    def probe_disk(self) -> ProbeResult:
        start = time.perf_counter()
        try:
            docs_dir = self.settings.docs_dir
            docs_dir.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(docs_dir)
            free_mb = usage.free / (1024 * 1024)
            latency = int((time.perf_counter() - start) * 1000)
            if free_mb < 256:
                return ProbeResult("disk", "degraded", latency, f"Low disk space: {free_mb:.0f} MB free")
            return ProbeResult("disk", "ok", latency, f"{free_mb:.0f} MB free")
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("disk", "degraded", latency, str(exc))

    def probe_llm(self) -> ProbeResult:
        start = time.perf_counter()
        if not self.settings.llm_api_key:
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("llm_system", "degraded", latency, "LLM_API_KEY not configured")
        try:
            self.llm.chat_completion("ping", temperature=0.0)
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("llm_system", "ok", latency)
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("llm_system", "degraded", latency, str(exc))

    def probe_embeddings(self) -> ProbeResult:
        start = time.perf_counter()
        if not self.settings.llm_api_key:
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("embeddings_system", "degraded", latency, "LLM_API_KEY not configured")
        try:
            self.llm.get_embedding("ping")
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("embeddings_system", "ok", latency)
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("embeddings_system", "degraded", latency, str(exc))

    def probe_queue(self) -> ProbeResult:
        start = time.perf_counter()
        try:
            pending = self.queue.count_by_status(["pending", "running"])
            dlq = self.queue.count_dlq()
            stuck = self.queue.count_stuck_jobs(self.settings.health_queue_stuck_sec)
            latency = int((time.perf_counter() - start) * 1000)
            if stuck > 0:
                return ProbeResult(
                    "queue",
                    "degraded",
                    latency,
                    f"pending={pending}, dlq={dlq}, stuck={stuck}",
                )
            if dlq > 0:
                return ProbeResult("queue", "degraded", latency, f"pending={pending}, dlq={dlq}")
            return ProbeResult("queue", "ok", latency, f"pending={pending}, dlq={dlq}")
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("queue", "down", latency, str(exc))

    def probe_worker(self) -> ProbeResult:
        start = time.perf_counter()
        try:
            pending = self.queue.count_by_status(["pending", "running"])
            last_seen = self.queue.worker_last_seen()
            latency = int((time.perf_counter() - start) * 1000)
            if last_seen is None:
                if pending > 0:
                    return ProbeResult("worker", "down", latency, "No worker heartbeat")
                return ProbeResult("worker", "degraded", latency, "No worker heartbeat")
            age_sec = (datetime.now(timezone.utc) - last_seen.astimezone(timezone.utc)).total_seconds()
            if age_sec > self.settings.health_worker_stale_sec:
                status = "down" if pending > 0 else "degraded"
                return ProbeResult("worker", status, latency, f"Stale heartbeat ({int(age_sec)}s)")
            return ProbeResult("worker", "ok", latency, f"Heartbeat {int(age_sec)}s ago")
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - start) * 1000)
            return ProbeResult("worker", "down", latency, str(exc))

    @staticmethod
    def overall_status(components: list[ProbeResult]) -> str:
        statuses = {item.status for item in components}
        if "down" in statuses:
            return "down"
        if "degraded" in statuses:
            return "degraded"
        return "ok"

    def run_probes(self, *, deep: bool = False) -> list[ProbeResult]:
        probes = [
            self.probe_postgres(),
            self.probe_migrations(),
            self.probe_disk(),
            self.probe_queue(),
            self.probe_worker(),
        ]
        if deep:
            probes.extend([self.probe_llm(), self.probe_embeddings()])
        return probes

    def build_health_response(self, *, deep: bool = False, user_id: str | None = None) -> HealthResponse:
        try:
            if user_id:
                chunks = self.repo.count_chunks(user_id)
                docs = self.repo.count_documents(user_id)
                indexing_count = self.repo.count_documents_by_status(user_id, ["indexing", "pending"])
                pending_count = self.repo.count_documents_by_status(user_id, ["pending"])
            else:
                chunks = 0
                docs = 0
                indexing_count = 0
                pending_count = 0
        except Exception as exc:  # noqa: BLE001
            chunks = 0
            docs = 0
            indexing_count = 0
            pending_count = 0
            index_error = f"count_failed: {exc}"
        else:
            index_error = None

        components = self.run_probes(deep=deep)
        overall = self.overall_status(components)
        queue_pending = (
            self.queue.count_by_status(["pending", "running"], user_id=user_id)
            if user_id
            else self.queue.count_by_status(["pending", "running"])
        )
        queue_failed = self.queue.count_dlq()

        index_ready = queue_pending == 0 and indexing_count == 0 and index_error is None
        status = overall
        if index_error:
            status = "degraded"
        elif docs > 0 and chunks == 0 and pending_count == 0 and queue_pending == 0:
            status = "degraded" if status == "ok" else status

        return HealthResponse(
            status=status,
            overall=overall,
            index_ready=index_ready,
            indexing_started=queue_pending > 0 or indexing_count > 0,
            indexing_done=queue_pending == 0 and pending_count == 0,
            rag_chunk_count=chunks,
            document_count=docs,
            indexing_count=indexing_count,
            pending_count=pending_count,
            index_error=index_error,
            queue_pending=queue_pending,
            queue_failed=queue_failed,
            components=[
                HealthComponent(
                    name=item.name,
                    status=item.status,
                    latency_ms=item.latency_ms,
                    message=item.message,
                )
                for item in components
            ],
        )

    def live(self) -> dict[str, str]:
        return {"status": "ok"}

    def ready(self) -> tuple[dict[str, str], int]:
        postgres = self.probe_postgres()
        migrations = self.probe_migrations()
        if postgres.status == "down" or migrations.status == "down":
            return {"status": "not_ready", "postgres": postgres.status, "migrations": migrations.status}, 503
        return {"status": "ready"}, 200
