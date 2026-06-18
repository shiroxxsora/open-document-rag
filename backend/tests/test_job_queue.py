import uuid

import pytest

from app.job_queue import classify_error, retry_delay_seconds


def test_classify_error_transient_http_codes():
    retryable, _ = classify_error("LLM API error: HTTP 503 Service Unavailable")
    assert retryable is True


def test_classify_error_permanent_http_codes():
    retryable, _ = classify_error("LLM API error: HTTP 401 Unauthorized")
    assert retryable is False


def test_retry_delay_seconds_backoff():
    assert retry_delay_seconds(1) == 30
    assert retry_delay_seconds(2) == 120
    assert retry_delay_seconds(99) == 1800


@pytest.mark.integration
def test_enqueue_claim_complete(job_queue):
    job_id = job_queue.enqueue("index_document", {"document_id": "sample.txt"})
    job = None
    for _ in range(20):
        candidate = job_queue.claim("test-worker")
        if candidate is None:
            break
        if candidate.id == job_id:
            job = candidate
            break
        job_queue.complete(candidate.id)
    assert job is not None
    assert job.job_type == "index_document"
    job_queue.complete(job.id)


@pytest.mark.integration
def test_cancel_indexing_jobs(job_queue):
    user_id = f"cancel-test-user-{uuid.uuid4()}"
    document_id = f"sample-{uuid.uuid4()}.txt"
    job_id = job_queue.enqueue(
        "index_document",
        {"document_id": document_id, "user_id": user_id},
        user_id=user_id,
    )
    cancelled = job_queue.cancel_indexing_jobs(user_id, document_id=document_id)
    assert cancelled == 1
    job = job_queue.claim("test-worker")
    if job is not None and job.id != job_id:
        job_queue.complete(job.id)
        job = job_queue.claim("test-worker")
    assert job is None or job.id != job_id


@pytest.mark.integration
def test_fail_retries_then_dlq(job_queue):
    job_id = job_queue.enqueue("index_document", {"document_id": "bad.txt"}, max_attempts=1)
    job = job_queue.claim("test-worker")
    assert job is not None
    job_queue.fail(job, "HTTP 503 upstream unavailable")
    assert job_queue.count_dlq() >= 1
    _ = job_id
