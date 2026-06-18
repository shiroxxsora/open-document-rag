import pytest

from app.config import load_settings
from tests.test_auth_jwt import login_dev


@pytest.mark.integration
def test_create_app_and_token_flow(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "dev-token@example.com")

    app_response = client.post(
        "/api/v1/developer/applications",
        json={"name": "Test App", "description": "integration"},
    )
    assert app_response.status_code == 200
    app_id = app_response.json()["app_id"]

    token_response = client.post(
        f"/api/v1/developer/applications/{app_id}/tokens",
        json={"scopes": ["chat:write", "documents:read"]},
    )
    assert token_response.status_code == 200
    body = token_response.json()
    raw_token = body["raw_token"]
    assert raw_token.startswith("srbs_live_")

    chat_response = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={"question": "hello"},
    )
    assert chat_response.status_code in {200, 400, 502}

    docs_response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert docs_response.status_code == 200

    forbidden = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {raw_token}"},
        files={"files": ("note.txt", b"hello", "text/plain")},
    )
    assert forbidden.status_code == 403

    revoke = client.delete(f"/api/v1/developer/tokens/{body['token_id']}")
    assert revoke.status_code == 204

    revoked = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert revoked.status_code == 401


@pytest.mark.integration
def test_developer_endpoints_reject_api_token(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "dev-owner@example.com")
    app_response = client.post("/api/v1/developer/applications", json={"name": "Owner App"})
    app_id = app_response.json()["app_id"]
    token_response = client.post(
        f"/api/v1/developer/applications/{app_id}/tokens",
        json={"scopes": ["chat:write"]},
    )
    raw_token = token_response.json()["raw_token"]
    response = client.get(
        "/api/v1/developer/applications",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert response.status_code == 403
