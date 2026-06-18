import io
import zipfile

import pytest

from app.config import load_settings
from tests.test_auth_jwt import login_dev


@pytest.mark.integration
def test_me_export_zip(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "export@example.com")
    response = client.get("/api/v1/me/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "export.json" in names
        payload = archive.read("export.json").decode("utf-8")
        assert "export@example.com" in payload


@pytest.mark.integration
def test_delete_me_removes_account(client):
    settings = load_settings()
    if settings.auth_mode != "dev":
        pytest.skip("AUTH_MODE is not dev")
    login_dev(client, "delete-me@example.com")
    response = client.delete("/api/v1/me")
    assert response.status_code == 204
    me = client.get("/api/v1/me")
    assert me.status_code == 401
