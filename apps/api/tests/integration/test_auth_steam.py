"""Steam sign-in: the assertion is only as good as Steam's own yes (Review Focus 1).

Pinned here: verification round-trips to Steam (a locally well-formed callback with
``is_valid:false`` opens nothing); a ``return_to`` minted for another origin — including
the other app —, a ``claimed_id`` that is not a Steam identity, an assertion that does
not sign the fields we rely on, and one not bound to this browser's sign-in nonce are
all refused before any network call; and the steamid becomes one ``users`` row however
many times it signs in.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest
import respx
from csmarket.core.config import Settings
from csmarket.core.errors import UnauthorizedError
from csmarket.modules.auth.models import RefreshToken
from csmarket.modules.auth.service import callback_url, steam_login
from csmarket.modules.auth.steam import SteamAuthError, build_login_url, verify_callback
from csmarket.modules.users.models import User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_OPENID = "https://steamcommunity.com/openid/login"
_SUMMARIES = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
WEB = Settings(
    environment="test",
    web_base_url="https://csmarket.uz",
    admin_base_url="https://admin.csmarket.uz",
)
KEYED = WEB.model_copy(update={"steam_api_key": "k"})


_CALLBACK = "https://csmarket.uz/auth/steam/callback"
#: The sign-in nonce this browser was given at ``/auth/steam/start`` (fake).
NONCE = "fake-nonce-0123456789ab"
_SIGNED = "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle"


def _params(
    *,
    return_to: str = f"{_CALLBACK}?locale=ru&n={NONCE}",
    sid: str = "76561198000000001",
    signed: str = _SIGNED,
) -> dict[str, str]:
    identity = f"https://steamcommunity.com/openid/id/{sid}"
    return {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.op_endpoint": _OPENID,
        "openid.claimed_id": identity,
        "openid.identity": identity,
        "openid.return_to": return_to,
        "openid.response_nonce": "2026-10-01T00:00:00Zfake",
        "openid.assoc_handle": "1234567890",
        "openid.signed": signed,
        "openid.sig": "ZmFrZS1zaWduYXR1cmU=",
    }


async def _users(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


async def _sessions(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(RefreshToken))).scalar_one()


def _fixed(steam_id: int) -> Callable[..., Awaitable[int]]:
    async def verify(params: dict[str, str], **_: object) -> int:
        return steam_id

    return verify


def test_callback_urls_per_app() -> None:
    assert callback_url(WEB, "web") == "https://csmarket.uz/auth/steam/callback"
    assert callback_url(WEB, "admin") == "https://admin.csmarket.uz/auth/steam/callback"


def test_login_url_carries_realm_and_return() -> None:
    url = build_login_url(
        return_to="https://csmarket.uz/auth/steam/callback", realm="https://csmarket.uz"
    )
    assert url.startswith(_OPENID)
    assert "checkid_setup" in url
    assert "csmarket.uz" in url


@respx.mock
async def test_verify_round_trips_to_steam_and_returns_the_id() -> None:
    route = respx.post(_OPENID).mock(
        return_value=httpx.Response(
            200, text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"
        )
    )
    steam_id = await verify_callback(_params(), expected_return_to=_CALLBACK, nonce=NONCE)
    assert steam_id == 76561198000000001
    sent = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert sent["openid.mode"] == "check_authentication"


@respx.mock
async def test_steam_saying_no_is_the_end_of_it() -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    with pytest.raises(SteamAuthError):
        await verify_callback(_params(), expected_return_to=_CALLBACK, nonce=NONCE)


@respx.mock
async def test_steam_unreachable_is_a_refusal() -> None:
    respx.post(_OPENID).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(SteamAuthError):
        await verify_callback(_params(), expected_return_to=_CALLBACK, nonce=NONCE)


@respx.mock
async def test_a_foreign_return_to_never_reaches_steam() -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = _params(return_to="https://evil.example/steal")
    with pytest.raises(SteamAuthError):
        await verify_callback(params, expected_return_to=_CALLBACK, nonce=NONCE)
    assert not route.called


@respx.mock
async def test_a_non_steam_claimed_id_is_refused_before_any_traffic() -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = _params()
    params["openid.claimed_id"] = "https://evil.example/openid/id/76561198000000001"
    with pytest.raises(SteamAuthError):
        await verify_callback(params, expected_return_to=_CALLBACK, nonce=NONCE)
    assert not route.called


@respx.mock
async def test_an_admin_assertion_cannot_open_a_web_session(db_session: AsyncSession) -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))

    async def verifier(params: dict[str, str], *, expected_return_to: str, nonce: str) -> int:
        return await verify_callback(params, expected_return_to=expected_return_to, nonce=nonce)

    with pytest.raises(UnauthorizedError):
        await steam_login(
            db_session,
            _params(return_to=f"https://admin.csmarket.uz/auth/steam/callback?n={NONCE}"),
            app="web",
            settings=WEB,
            nonce=NONCE,
            verifier=verifier,
        )
    assert not route.called
    assert await _users(db_session) == 0


@respx.mock
async def test_steam_saying_no_creates_nobody(db_session: AsyncSession) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    with pytest.raises(UnauthorizedError):
        await steam_login(db_session, _params(), app="web", settings=WEB, nonce=NONCE)
    assert await _users(db_session) == 0
    assert await _sessions(db_session) == 0


@respx.mock
async def test_valid_assertion_signs_in_and_stores_steam_id_as_text(
    db_session: AsyncSession,
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    tokens = await steam_login(db_session, _params(), app="web", settings=WEB, nonce=NONCE)
    await db_session.commit()
    assert tokens.user.steam_id == "76561198000000001"
    assert tokens.access_token
    assert tokens.refresh_token


@respx.mock
async def test_the_admin_app_verifies_against_its_own_callback(db_session: AsyncSession) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = _params(return_to=f"https://admin.csmarket.uz/auth/steam/callback?locale=ru&n={NONCE}")
    tokens = await steam_login(db_session, params, app="admin", settings=WEB, nonce=NONCE)
    assert tokens.user.steam_id == "76561198000000001"


async def test_steam_login_creates_one_account_and_reuses_it(db_session: AsyncSession) -> None:
    first = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=WEB,
        nonce=NONCE,
        verifier=_fixed(76561198000000042),
    )
    second = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=WEB,
        nonce=NONCE,
        verifier=_fixed(76561198000000042),
    )
    assert first.access_token
    assert second.access_token
    assert first.user.id == second.user.id
    assert await _users(db_session) == 1


async def test_a_rejected_assertion_is_a_401(db_session: AsyncSession) -> None:
    async def verify(params: dict[str, str], **_: object) -> int:
        raise SteamAuthError("nope")

    with pytest.raises(UnauthorizedError):
        await steam_login(
            db_session, _params(), app="web", settings=WEB, nonce=NONCE, verifier=verify
        )


async def test_no_api_key_means_no_persona_call(db_session: AsyncSession) -> None:
    async def persona(*_: object, **__: object) -> tuple[str | None, str | None]:
        raise AssertionError("persona must not be fetched without a key")

    tokens = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=WEB,
        nonce=NONCE,
        verifier=_fixed(76561198000000043),
        persona=persona,
    )
    assert tokens.user.display_name is None


@respx.mock
async def test_persona_fetch_failure_never_breaks_the_login(db_session: AsyncSession) -> None:
    respx.get(_SUMMARIES).mock(return_value=httpx.Response(500))
    tokens = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=KEYED,
        nonce=NONCE,
        verifier=_fixed(76561198000000077),
    )
    assert tokens.access_token
    assert tokens.user.display_name is None  # nameless, not broken


@respx.mock
async def test_an_empty_players_array_still_signs_the_user_in_nameless(
    db_session: AsyncSession,
) -> None:
    """OpenID has already proven the account exists; an empty ``players`` is a Steam
    oddity here, not grounds to refuse a sign-in."""
    respx.get(_SUMMARIES).mock(return_value=httpx.Response(200, json={"response": {"players": []}}))
    tokens = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=KEYED,
        nonce=NONCE,
        verifier=_fixed(76561198000000078),
    )
    assert tokens.access_token
    assert tokens.user.display_name is None


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"response": {}},
        {"response": {"players": None}},
        [],
        "not an object at all",
        {"response": {"players": [None]}},
        {"response": {"players": ["not an object"]}},
    ],
)
async def test_a_degraded_summaries_body_still_signs_the_user_in_nameless(
    db_session: AsyncSession, body: object
) -> None:
    """A 200 shaped wrong is a ValueError, which ``fetch_persona`` folds into a nameless
    sign-in — never an AttributeError that would 500 it."""
    respx.get(_SUMMARIES).mock(return_value=httpx.Response(200, json=body))
    tokens = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=KEYED,
        nonce=NONCE,
        verifier=_fixed(76561198000000079),
    )
    assert tokens.access_token
    assert tokens.user.display_name is None


@respx.mock
async def test_persona_and_avatar_land_on_the_profile(db_session: AsyncSession) -> None:
    respx.get(_SUMMARIES).mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "players": [
                        {
                            "personaname": "jama",
                            "avatarfull": "https://avatars.steamstatic.com/x_full.jpg",
                        }
                    ]
                }
            },
        )
    )
    tokens = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=KEYED,
        nonce=NONCE,
        verifier=_fixed(76561198000000088),
    )
    assert tokens.user.display_name == "jama"
    assert tokens.user.avatar_url == "https://avatars.steamstatic.com/x_full.jpg"


@respx.mock
async def test_a_sign_in_counts_against_the_shared_steam_quota(db_session: AsyncSession) -> None:
    """The persona call spends the Steam Web API key; OpenID's own round trip carries no
    key and is deliberately not counted."""
    from prometheus_client import REGISTRY

    def calls() -> float:
        labels = {"endpoint": "get_player_summaries", "consumer": "auth_signin", "outcome": "ok"}
        return REGISTRY.get_sample_value("csmarket_steam_web_api_calls_total", labels) or 0.0

    respx.get(_SUMMARIES).mock(
        return_value=httpx.Response(200, json={"response": {"players": [{"personaname": "j"}]}})
    )
    before = calls()
    await steam_login(
        db_session,
        _params(),
        app="web",
        settings=KEYED,
        nonce=NONCE,
        verifier=_fixed(76561198000000099),
    )
    assert calls() == before + 1


# --- Binding to the browser that started sign-in (login CSRF) ------------------------


@respx.mock
@pytest.mark.parametrize(
    ("return_to", "nonce"),
    [
        # The browser never ran /auth/steam/start: no cookie, no nonce.
        (f"{_CALLBACK}?locale=ru&n={NONCE}", None),
        # An attacker's own assertion, minted for the attacker's nonce.
        (f"{_CALLBACK}?locale=ru&n=attacker-nonce-000000", NONCE),
        # An assertion that carries no nonce at all.
        (f"{_CALLBACK}?locale=ru", NONCE),
        # The nonce must be the whole value, not a prefix of it.
        (f"{_CALLBACK}?locale=ru&n={NONCE}x", NONCE),
        # Two nonces: ambiguous, refused.
        (f"{_CALLBACK}?n={NONCE}&n=other", NONCE),
    ],
)
async def test_an_assertion_not_bound_to_this_browser_never_reaches_steam(
    return_to: str, nonce: str | None
) -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    with pytest.raises(SteamAuthError):
        await verify_callback(
            _params(return_to=return_to), expected_return_to=_CALLBACK, nonce=nonce
        )
    assert not route.called


@respx.mock
@pytest.mark.parametrize(
    "return_to",
    [
        f"{_CALLBACK}x?n={NONCE}",  # a longer path that merely starts with ours
        f"{_CALLBACK}/../evil?n={NONCE}",
        f"https://csmarket.uz.evil.example/auth/steam/callback?n={NONCE}",
        f"http://csmarket.uz/auth/steam/callback?n={NONCE}",  # scheme downgrade
    ],
)
async def test_return_to_must_be_exactly_our_callback(return_to: str) -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    with pytest.raises(SteamAuthError):
        await verify_callback(
            _params(return_to=return_to), expected_return_to=_CALLBACK, nonce=NONCE
        )
    assert not route.called


@respx.mock
@pytest.mark.parametrize(
    "missing", ["claimed_id", "identity", "return_to", "response_nonce", "assoc_handle"]
)
async def test_an_assertion_must_sign_every_field_we_rely_on(missing: str) -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    signed = ",".join(f for f in _SIGNED.split(",") if f != missing)
    with pytest.raises(SteamAuthError):
        await verify_callback(_params(signed=signed), expected_return_to=_CALLBACK, nonce=NONCE)
    assert not route.called


@respx.mock
async def test_an_assertion_without_a_signed_list_is_refused() -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = _params()
    del params["openid.signed"]
    with pytest.raises(SteamAuthError):
        await verify_callback(params, expected_return_to=_CALLBACK, nonce=NONCE)
    assert not route.called


async def test_steam_login_refuses_a_foreign_nonce_and_writes_nothing(
    db_session: AsyncSession,
) -> None:
    with respx.mock:
        route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
        with pytest.raises(UnauthorizedError):
            await steam_login(
                db_session, _params(), app="web", settings=WEB, nonce="someone-else-000000"
            )
        assert not route.called
    assert await _users(db_session) == 0
    assert await _sessions(db_session) == 0


# --- What a refusal may say ----------------------------------------------------------


@respx.mock
async def test_an_unreachable_steam_error_carries_no_transport_text() -> None:
    """httpx messages can carry URLs and the params we sent; none of it goes in the error."""
    respx.post(_OPENID).mock(side_effect=httpx.ConnectTimeout("upstream said steamid=7656"))
    with pytest.raises(SteamAuthError) as info:
        await verify_callback(_params(), expected_return_to=_CALLBACK, nonce=NONCE)
    assert str(info.value) == "steam unreachable"


async def test_a_refusal_logs_the_reason_and_error_type_only(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from csmarket.modules.auth import service as svc

    calls: list[tuple[str, dict[str, object]]] = []

    class _Log:
        def info(self, event: str, **kw: object) -> None:
            calls.append((event, kw))

    monkeypatch.setattr(svc, "log", _Log())

    async def verify(params: dict[str, str], **_: object) -> int:
        try:
            raise httpx.ConnectTimeout("secret transport text 76561198000000001")
        except httpx.HTTPError as exc:
            raise SteamAuthError("steam unreachable") from exc

    with pytest.raises(UnauthorizedError):
        await steam_login(
            db_session, _params(), app="web", settings=WEB, nonce=NONCE, verifier=verify
        )
    assert calls == [
        (
            "auth.steam.rejected",
            {"reason": "steam unreachable", "error": "ConnectTimeout", "app": "web"},
        )
    ]
