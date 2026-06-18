import os

import pytest

from app.config import load_settings
from tests.test_auth_jwt import login_dev


@pytest.fixture(autouse=True)
def enable_mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")


@pytest.mark.integration
def test_multiturn_uses_session_id(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "multiturn@example.com")
    client.put("/api/v1/me/settings", json={"llm_api_key": "test-key"})
    first = client.post("/api/v1/chat", json={"question": "First question"})
    assert first.status_code == 200
    session_id = first.json()["session_id"]
    second = client.post(
        "/api/v1/chat",
        json={"question": "Follow-up question", "session_id": session_id},
    )
    assert second.status_code == 200
    assert "Mock follow-up" in second.json()["answer"]
    assert second.json()["session_id"] == session_id
