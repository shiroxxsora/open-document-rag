import json
import os

import pytest

from app.config import load_settings
from tests.test_auth_jwt import login_dev


@pytest.fixture(autouse=True)
def enable_mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")


@pytest.mark.integration
def test_chat_stream_emits_token_events(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "sse@example.com")
    client.put("/api/v1/me/settings", json={"llm_api_key": "test-key"})
    with client.stream("POST", "/api/v1/chat/stream", json={"question": "Stream please"}) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        assert any(event.get("type") == "token" for event in events)
        done = next(event for event in events if event.get("type") == "done")
        assert done["session_id"]
        assert done["answer"]
