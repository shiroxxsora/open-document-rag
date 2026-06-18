import pytest

from app.config import load_settings
from tests.test_auth_jwt import login_dev


@pytest.fixture
def service():
    from app.service import RAGService

    settings = load_settings()
    return RAGService(settings)


@pytest.mark.integration
def test_delete_document_path_traversal_returns_400(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client)
    response = client.delete("/api/v1/documents/../../etc/passwd")
    assert response.status_code in (400, 404, 422)


@pytest.mark.integration
def test_reindex_missing_document_404(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client)
    response = client.post("/api/v1/documents/does-not-exist-xyz/reindex")
    assert response.status_code == 404


@pytest.mark.integration
def test_cancel_indexing_when_idle_400(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client)
    response = client.post("/api/v1/cancel-indexing")
    assert response.status_code == 400


def test_health_live_ok(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready_endpoint(client):
    response = client.get("/health/ready")
    assert response.status_code in (200, 503)
