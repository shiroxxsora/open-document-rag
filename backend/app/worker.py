from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import Settings
from app.job_queue import Job, JobQueue
from app.service import IndexingCancelledError, RAGService
from app.usage import UsageService
from app.webhooks import deliver_webhook, enqueue_indexing_webhooks

logger = logging.getLogger(__name__)


def _handle_index_document(service: RAGService, queue: JobQueue, job: Job) -> None:
    document_id = str(job.payload.get("document_id", "")).strip()
    user_id = (job.user_id or str(job.payload.get("user_id", ""))).strip()
    if not document_id or not user_id:
        raise ValueError("index_document job requires document_id and user_id")
    try:
        service.index_uploaded_document(user_id, document_id)
        enqueue_indexing_webhooks(
            service.settings,
            queue,
            user_id=user_id,
            document_id=document_id,
            event="indexing.completed",
        )
    except Exception as exc:
        enqueue_indexing_webhooks(
            service.settings,
            queue,
            user_id=user_id,
            document_id=document_id,
            event="indexing.failed",
            error=str(exc),
        )
        raise


def _handle_full_reindex(service: RAGService, job: Job) -> None:
    user_id = (job.user_id or str(job.payload.get("user_id", ""))).strip()
    if not user_id:
        raise ValueError("full_reindex job requires user_id")
    full_resync = bool(job.payload.get("full_resync", True))
    service.index_documents(user_id, full_resync=full_resync)


def _handle_webhook_deliver(settings: Settings, job: Job) -> None:
    webhook_url = str(job.payload.get("webhook_url", "")).strip()
    app_id = str(job.payload.get("app_id", "")).strip()
    event = str(job.payload.get("event", "")).strip()
    document_id = str(job.payload.get("document_id", "")).strip() or None
    error = str(job.payload.get("error", "")).strip() or None
    user_id = (job.user_id or "").strip()
    if not webhook_url or not app_id or not event or not user_id:
        raise ValueError("webhook_deliver job requires webhook_url, app_id, event, and user_id")
    if not webhook_url.startswith(("http://", "https://")):
        raise ValueError("Invalid webhook URL")
    deliver_webhook(
        settings,
        webhook_url=webhook_url,
        app_id=app_id,
        event=event,
        user_id=user_id,
        document_id=document_id,
        error=error,
    )


JOB_HANDLERS = {
    "index_document": _handle_index_document,
    "full_reindex": _handle_full_reindex,
    "webhook_deliver": _handle_webhook_deliver,
}


def process_job(service: RAGService, queue: JobQueue, job: Job) -> None:
    handler = JOB_HANDLERS.get(job.job_type)
    if handler is None:
        queue.fail(job, f"Unknown job_type: {job.job_type}", permanent=True)
        return
    try:
        if job.job_type == "webhook_deliver":
            handler(service.settings, job)
        elif job.job_type == "index_document":
            handler(service, queue, job)
        else:
            handler(service, job)
        if queue.is_job_running(job.id):
            queue.complete(job.id)
            logger.info("Completed job %s type=%s", job.id, job.job_type)
    except IndexingCancelledError:
        logger.info("Indexing cancelled for job %s type=%s", job.id, job.job_type)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s failed", job.id)
        if queue.is_job_running(job.id):
            queue.fail(job, exc)


def run_worker(settings: Settings) -> None:
    usage = UsageService(settings)
    service = RAGService(settings, usage=usage)
    queue = JobQueue(settings)
    service.bootstrap()
    queue.requeue_stale_running_jobs(settings.health_worker_stale_sec)
    logger.info(
        "Worker %s started (concurrency=%s, poll=%ss)",
        settings.job_worker_id,
        settings.job_worker_concurrency,
        settings.job_worker_poll_interval_sec,
    )

    with ThreadPoolExecutor(max_workers=settings.job_worker_concurrency) as pool:
        while True:
            queue.touch_worker_heartbeat(settings.job_worker_id)
            claimed: list[Job] = []
            for _ in range(settings.job_worker_concurrency):
                job = queue.claim(settings.job_worker_id)
                if job is None:
                    break
                claimed.append(job)

            if not claimed:
                time.sleep(settings.job_worker_poll_interval_sec)
                continue

            futures = [pool.submit(process_job, service, queue, job) for job in claimed]
            for future in as_completed(futures):
                future.result()


def main() -> None:
    from app.config import load_settings

    logging.basicConfig(level=logging.INFO)
    run_worker(load_settings())


if __name__ == "__main__":
    main()
