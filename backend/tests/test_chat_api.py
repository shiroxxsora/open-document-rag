import json
import os

import pytest

from app.config import load_settings
from tests.test_auth_jwt import login_dev


@pytest.fixture(autouse=True)
def enable_mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")


@pytest.mark.integration
def test_chat_requires_llm_key(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "chat-no-key@example.com")
    response = client.post("/api/v1/chat", json={"question": "hello"})
    assert response.status_code == 400
    assert "LLM API key" in response.json()["detail"]


@pytest.mark.integration
def test_chat_with_key_returns_answer(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "chat-key@example.com")
    save = client.put(
        "/api/v1/me/settings",
        json={"llm_api_key": "test-key", "llm_model": "mock-model"},
    )
    assert save.status_code == 200
    response = client.post("/api/v1/chat", json={"question": "What is SRBS?"})
    assert response.status_code == 200
    body = response.json()
    assert "Mock answer" in body["answer"]
    assert body["session_id"]


@pytest.mark.integration
def test_test_llm_endpoint(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "test-llm@example.com")
    client.put("/api/v1/me/settings", json={"llm_api_key": "test-key"})
    response = client.post("/api/v1/me/settings/test-llm")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
