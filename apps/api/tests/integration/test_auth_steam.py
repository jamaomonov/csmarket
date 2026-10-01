"""Steam sign-in: the assertion is only as good as Steam's own yes (Review Focus 1).

Pinned here: verification round-trips to Steam (a locally well-formed callback with
``is_valid:false`` opens nothing), a ``return_to`` minted for another origin — including
the other app — and a ``claimed_id`` that is not a Steam identity are refused before any
network call, and the steamid becomes one ``users`` row however many times it signs in.
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


def _params(
    *,
    return_to: str = "https://csmarket.uz/auth/steam/callback?locale=ru",
    sid: str = "76561198000000001",
) -> dict[str, str]:
    return {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{sid}",
        "openid.return_to": return_to,
        "openid.sig": "sig",
        "openid.signed": "signed,fields",
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
    steam_id = await verify_callback(
        _params(), expected_return_prefix="https://csmarket.uz/auth/steam/callback"
    )
    assert steam_id == 76561198000000001
    sent = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert sent["openid.mode"] == "check_authentication"


@respx.mock
async def test_steam_saying_no_is_the_end_of_it() -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    with pytest.raises(SteamAuthError):
        await verify_callback(
            _params(), expected_return_prefix="https://csmarket.uz/auth/steam/callback"
        )


@respx.mock
async def test_steam_unreachable_is_a_refusal() -> None:
    respx.post(_OPENID).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(SteamAuthError):
        await verify_callback(
            _params(), expected_return_prefix="https://csmarket.uz/auth/steam/callback"
        )


@respx.mock
async def test_a_foreign_return_to_never_reaches_steam() -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = _params(return_to="https://evil.example/steal")
    with pytest.raises(SteamAuthError):
        await verify_callback(
            params, expected_return_prefix="https://csmarket.uz/auth/steam/callback"
        )
    assert not route.called


@respx.mock
async def test_a_non_steam_claimed_id_is_refused_before_any_traffic() -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = _params()
    params["openid.claimed_id"] = "https://evil.example/openid/id/76561198000000001"
    with pytest.raises(SteamAuthError):
        await verify_callback(
            params, expected_return_prefix="https://csmarket.uz/auth/steam/callback"
        )
    assert not route.called


@respx.mock
async def test_an_admin_assertion_cannot_open_a_web_session(db_session: AsyncSession) -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))

    async def verifier(params: dict[str, str], *, expected_return_prefix: str) -> int:
        return await verify_callback(params, expected_return_prefix=expected_return_prefix)

    with pytest.raises(UnauthorizedError):
        await steam_login(
            db_session,
            _params(return_to="https://admin.csmarket.uz/auth/steam/callback"),
            app="web",
            settings=WEB,
            verifier=verifier,
        )
    assert not route.called
    assert await _users(db_session) == 0


@respx.mock
async def test_steam_saying_no_creates_nobody(db_session: AsyncSession) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    with pytest.raises(UnauthorizedError):
        await steam_login(db_session, _params(), app="web", settings=WEB)
    assert await _users(db_session) == 0
    assert await _sessions(db_session) == 0


@respx.mock
async def test_valid_assertion_signs_in_and_stores_steam_id_as_text(
    db_session: AsyncSession,
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    tokens = await steam_login(db_session, _params(), app="web", settings=WEB)
    await db_session.commit()
    assert tokens.user.steam_id == "76561198000000001"
    assert tokens.access_token
    assert tokens.refresh_token


@respx.mock
async def test_the_admin_app_verifies_against_its_own_callback(db_session: AsyncSession) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = _params(return_to="https://admin.csmarket.uz/auth/steam/callback?locale=ru")
    tokens = await steam_login(db_session, params, app="admin", settings=WEB)
    assert tokens.user.steam_id == "76561198000000001"


async def test_steam_login_creates_one_account_and_reuses_it(db_session: AsyncSession) -> None:
    first = await steam_login(
        db_session, _params(), app="web", settings=WEB, verifier=_fixed(76561198000000042)
    )
    second = await steam_login(
        db_session, _params(), app="web", settings=WEB, verifier=_fixed(76561198000000042)
    )
    assert first.access_token
    assert second.access_token
    assert first.user.id == second.user.id
    assert await _users(db_session) == 1


async def test_a_rejected_assertion_is_a_401(db_session: AsyncSession) -> None:
    async def verify(params: dict[str, str], **_: object) -> int:
        raise SteamAuthError("nope")

    with pytest.raises(UnauthorizedError):
        await steam_login(db_session, _params(), app="web", settings=WEB, verifier=verify)


async def test_no_api_key_means_no_persona_call(db_session: AsyncSession) -> None:
    async def persona(*_: object, **__: object) -> tuple[str | None, str | None]:
        raise AssertionError("persona must not be fetched without a key")

    tokens = await steam_login(
        db_session,
        _params(),
        app="web",
        settings=WEB,
        verifier=_fixed(76561198000000043),
        persona=persona,
    )
    assert tokens.user.display_name is None


@respx.mock
async def test_persona_fetch_failure_never_breaks_the_login(db_session: AsyncSession) -> None:
    respx.get(_SUMMARIES).mock(return_value=httpx.Response(500))
    tokens = await steam_login(
        db_session, _params(), app="web", settings=KEYED, verifier=_fixed(76561198000000077)
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
        db_session, _params(), app="web", settings=KEYED, verifier=_fixed(76561198000000078)
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
        db_session, _params(), app="web", settings=KEYED, verifier=_fixed(76561198000000079)
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
        db_session, _params(), app="web", settings=KEYED, verifier=_fixed(76561198000000088)
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
        db_session, _params(), app="web", settings=KEYED, verifier=_fixed(76561198000000099)
    )
    assert calls() == before + 1
