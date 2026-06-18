import pytest
from fastapi import HTTPException

from app.usage import UsageService
from tests.conftest import test_settings


@pytest.fixture
def usage_service(test_settings):
    return UsageService(test_settings)


@pytest.mark.integration
def test_increment_and_build_response(usage_service):
    user_id = "usage-test-user"
    usage_service.increment(user_id, chat_requests=2, upload_bytes=1024)
    response = usage_service.build_response(user_id)
    assert response.usage.chat_requests >= 2
    assert response.limits.max_chat_per_day >= 1


@pytest.mark.integration
def test_chat_quota_returns_429(usage_service, test_settings):
    user_id = "quota-blocked-user"
    limits = usage_service.get_limits(user_id)
    usage_service.increment(user_id, chat_requests=limits.max_chat_per_day)
    with pytest.raises(HTTPException) as exc:
        usage_service.check_chat_quota(user_id)
    assert exc.value.status_code == 429
    assert exc.value.headers.get("Retry-After") == "86400"
