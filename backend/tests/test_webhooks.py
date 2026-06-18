import pytest

from app.webhooks import build_event_payload, sign_payload, signing_secret
from tests.conftest import test_settings as settings_fixture


def test_sign_payload_is_deterministic(settings_fixture):
    secret = signing_secret(settings_fixture, "app-123")
    body = b'{"event":"indexing.completed"}'
    assert sign_payload(secret, body) == sign_payload(secret, body)
    assert sign_payload(secret, body) != sign_payload(secret, b'{"event":"other"}')


def test_build_event_payload_includes_document(settings_fixture):
    payload = build_event_payload(
        event="indexing.failed",
        app_id="app-1",
        user_id="user-1",
        document_id="doc.txt",
        error="boom",
    )
    assert payload["event"] == "indexing.failed"
    assert payload["document_id"] == "doc.txt"
    assert payload["error"] == "boom"


@pytest.mark.integration
def test_webhook_deliver_job_invalid_url(job_queue):
    job_id = job_queue.enqueue(
        "webhook_deliver",
        {
            "app_id": "app-1",
            "webhook_url": "ftp://bad.example/hook",
            "event": "indexing.completed",
            "document_id": "doc.txt",
        },
        user_id="user-1",
    )
    job = job_queue.claim("test-worker")
    assert job is not None
    from app.worker import process_job
    from app.config import load_settings
    from app.service import RAGService

    service = RAGService(load_settings())
    process_job(service, job_queue, job)
    assert job_queue.count_dlq() >= 1
