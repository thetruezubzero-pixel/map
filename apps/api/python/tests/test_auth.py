import jwt as pyjwt
import pytest
from fastapi import HTTPException

from app import auth, config


class _FakeRequest:
    """require_user_id only ever calls request.headers.get(...) -- a real
    starlette.requests.Request isn't needed to exercise this function."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


def _set_jwt_secret(monkeypatch, value: str | None):
    if value is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", value)
    config.get_settings.cache_clear()


def test_require_user_id_fails_closed_when_secret_unset(monkeypatch):
    _set_jwt_secret(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        auth.require_user_id(_FakeRequest())
    assert exc.value.status_code == 503
    config.get_settings.cache_clear()


@pytest.mark.parametrize("placeholder", ["change-me-in-production"])
def test_require_user_id_fails_closed_on_known_placeholder_secret(monkeypatch, placeholder):
    """A "connect the dots" audit found that .env.example ships
    JWT_SECRET=change-me-in-production as a literal value, and
    docker-compose's ${JWT_SECRET:?...} guard only checks non-empty -- so
    copying the example file verbatim used to pass this function's old
    `not settings.jwt_secret` check too, silently leaving POST
    /architect/run (a route that can trigger a real git commit + PR)
    forgeable by anyone who's read this open-source repo's own example
    file. Must be rejected exactly like the missing-secret case."""
    _set_jwt_secret(monkeypatch, placeholder)
    with pytest.raises(HTTPException) as exc:
        auth.require_user_id(_FakeRequest())
    assert exc.value.status_code == 503
    config.get_settings.cache_clear()


def test_require_user_id_rejects_missing_bearer_token(monkeypatch):
    _set_jwt_secret(monkeypatch, "a-real-random-test-secret")
    with pytest.raises(HTTPException) as exc:
        auth.require_user_id(_FakeRequest())
    assert exc.value.status_code == 401
    config.get_settings.cache_clear()


def test_require_user_id_rejects_invalid_token(monkeypatch):
    _set_jwt_secret(monkeypatch, "a-real-random-test-secret")
    with pytest.raises(HTTPException) as exc:
        auth.require_user_id(_FakeRequest({"authorization": "Bearer not-a-real-token"}))
    assert exc.value.status_code == 401
    config.get_settings.cache_clear()


def test_require_user_id_accepts_a_real_valid_token(monkeypatch):
    _set_jwt_secret(monkeypatch, "a-real-random-test-secret")
    token = pyjwt.encode({"sub": "architect-cron"}, "a-real-random-test-secret", algorithm="HS256")
    sub = auth.require_user_id(_FakeRequest({"authorization": f"Bearer {token}"}))
    assert sub == "architect-cron"
    config.get_settings.cache_clear()


def test_require_user_id_rejects_token_missing_sub_claim(monkeypatch):
    _set_jwt_secret(monkeypatch, "a-real-random-test-secret")
    token = pyjwt.encode({"exp": 9999999999}, "a-real-random-test-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        auth.require_user_id(_FakeRequest({"authorization": f"Bearer {token}"}))
    assert exc.value.status_code == 401
    config.get_settings.cache_clear()
