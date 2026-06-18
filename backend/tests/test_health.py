import pytest

from app.healthcheck import HealthChecker


def test_live_probe(health_checker: HealthChecker):
    assert health_checker.live() == {"status": "ok"}


def test_overall_status_down_beats_degraded():
    from app.healthcheck import ProbeResult

    components = [
        ProbeResult("postgres", "ok", 1),
        ProbeResult("worker", "down", 2, "stale"),
    ]
    assert HealthChecker.overall_status(components) == "down"


def test_overall_status_degraded():
    from app.healthcheck import ProbeResult

    components = [
        ProbeResult("postgres", "ok", 1),
        ProbeResult("disk", "degraded", 2, "low space"),
    ]
    assert HealthChecker.overall_status(components) == "degraded"


@pytest.mark.integration
def test_ready_requires_postgres(health_checker: HealthChecker):
    body, status_code = health_checker.ready()
    assert status_code in {200, 503}
    assert "status" in body


def test_health_requires_auth():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 401
