import pytest
from fastapi.testclient import TestClient

from app.auth import AuthService
from app.config import load_settings


@pytest.fixture
def auth_service():
    return AuthService(load_settings())


def login_dev(client: TestClient, email: str = "test@example.com") -> str:
    response = client.post("/api/v1/auth/dev/login", json={"email": email, "display_name": "Tester"})
    assert response.status_code == 200
    token = response.cookies.get("srbs_session")
    assert token
    return token


def auth_headers(client: TestClient, email: str = "test@example.com") -> dict[str, str]:
    login_dev(client, email)
    return {}


@pytest.mark.integration
def test_dev_login_sets_cookie(client, auth_service):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    response = client.post("/api/v1/auth/dev/login", json={"email": "jwt@example.com"})
    assert response.status_code == 200
    assert client.cookies.get("srbs_session")
    assert response.json()["email"] == "jwt@example.com"


def test_protected_health_requires_auth(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 401


@pytest.mark.integration
def test_authenticated_health_ok(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert "components" in body


def test_expired_or_invalid_cookie_rejected(client, auth_service):
    client.cookies.set("srbs_session", "not-a-valid-jwt")
    response = client.get("/api/v1/documents")
    assert response.status_code == 401


@pytest.mark.integration
def test_logout_clears_session(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    response = client.get("/api/v1/documents")
    assert response.status_code == 401
