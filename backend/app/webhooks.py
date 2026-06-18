from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.api_tokens import ApiTokenService
from app.config import Settings
from app.job_queue import JobQueue

logger = logging.getLogger(__name__)


def signing_secret(settings: Settings, app_id: str) -> str:
    return f"{settings.auth_secret_key}:{app_id}"


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def build_event_payload(
    *,
    event: str,
    app_id: str,
    user_id: str,
    document_id: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": event,
        "app_id": app_id,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if document_id:
        payload["document_id"] = document_id
    if error:
        payload["error"] = error
    return payload


def deliver_webhook(
    settings: Settings,
    *,
    webhook_url: str,
    app_id: str,
    event: str,
    user_id: str,
    document_id: str | None = None,
    error: str | None = None,
) -> None:
    body_dict = build_event_payload(
        event=event,
        app_id=app_id,
        user_id=user_id,
        document_id=document_id,
        error=error,
    )
    body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
    secret = signing_secret(settings, app_id)
    signature = sign_payload(secret, body)
    request = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-SRBS-Event": event,
            "X-SRBS-Signature": f"sha256={signature}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} from webhook endpoint")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from webhook endpoint: {exc.read().decode('utf-8', errors='ignore')}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Webhook delivery timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"Webhook delivery failed: {exc!s}") from exc


def enqueue_indexing_webhooks(
    settings: Settings,
    queue: JobQueue,
    *,
    user_id: str,
    document_id: str,
    event: str,
    error: str | None = None,
) -> None:
    token_service = ApiTokenService(settings)
    for app in token_service.list_applications(user_id):
        if not app.webhook_url:
            continue
        queue.enqueue(
            "webhook_deliver",
            {
                "app_id": app.app_id,
                "webhook_url": app.webhook_url,
                "event": event,
                "document_id": document_id,
                "error": error,
            },
            user_id=user_id,
        )
