"""Refresh cookie attributes per environment (ruling P8: one cookie for web and admin)."""

from csmarket.core.config import Settings
from csmarket.modules.auth.cookies import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    set_refresh_cookie,
)
from fastapi import Response


def _cookie(settings: Settings) -> str:
    r = Response()
    set_refresh_cookie(r, token="t" * 43, max_age=60, settings=settings)
    return r.headers["set-cookie"]


def test_dev_cookie_is_host_only_and_not_secure() -> None:
    header = _cookie(Settings(environment="dev"))
    assert header.startswith(f"{REFRESH_COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Secure" not in header
    assert "Domain" not in header


def test_prod_cookie_is_secure_and_shared_by_web_and_admin() -> None:
    header = _cookie(Settings(environment="prod", web_base_url="https://csmarket.uz"))
    assert "Secure" in header
    assert "Domain=.csmarket.uz" in header


def test_cookie_name_and_path() -> None:
    header = _cookie(Settings(environment="dev"))
    assert REFRESH_COOKIE_NAME == "csmarket_refresh"
    assert "Path=/" in header
    assert "Max-Age=60" in header


def test_clear_matches_the_set_attributes() -> None:
    r = Response()
    clear_refresh_cookie(
        r, settings=Settings(environment="prod", web_base_url="https://csmarket.uz")
    )
    header = r.headers["set-cookie"]
    assert header.startswith(f"{REFRESH_COOKIE_NAME}=")
    assert "Max-Age=0" in header
    assert "Domain=.csmarket.uz" in header
    assert "Secure" in header


def test_prod_with_a_bare_host_stays_host_only() -> None:
    header = _cookie(Settings(environment="prod", web_base_url="http://localhost:3100"))
    assert "Domain" not in header
