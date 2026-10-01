"""Steam sign-in: OpenID 2.0, the only door Steam offers.

Steam never adopted OAuth: the browser is sent to
``steamcommunity.com/openid/login`` and comes back with a signed parameter
set. The ONLY trustworthy verification is handing that exact set back to
Steam with ``openid.mode=check_authentication`` — Steam answers
``is_valid:true`` once and marks the assertion used, which is also what
makes replays die at Steam's side rather than ours.

An external HTTP call on a request path is normally banned (AGENTS §11); this
one is the documented exception: it IS the authentication, it happens once per
login on a low-rate credential endpoint behind ``ip_guard``, and it is
bounded by a short timeout.

Steam's signature proves *who* signed in, not *which browser* asked. To stop login CSRF
(an attacker handing a victim their own Steam redirect and signing the victim into the
attacker's account), ``/auth/steam/start`` gives the browser a random nonce in an
``HttpOnly`` cookie and puts the same nonce into ``return_to`` as ``n``. Steam signs
``return_to``, so the completion accepts an assertion only when its signed ``n`` equals
the cookie this browser sends.

Identity is the steamid64 alone; ``users.steam_id`` holds it as text.
"""

from __future__ import annotations

import hmac
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from csmarket.core.metrics import SteamApiConsumer, steam_web_api_call

_STEAM_OPENID = "https://steamcommunity.com/openid/login"
_CLAIMED_ID = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{10,20})$")
_TIMEOUT_SECONDS = 10.0
#: The fields an assertion must sign for the checks below to mean anything: an
#: unsigned ``return_to`` would make the nonce binding decorative.
REQUIRED_SIGNED = frozenset(
    {"claimed_id", "identity", "return_to", "response_nonce", "assoc_handle"}
)
#: The ``return_to`` query parameter carrying the sign-in nonce.
NONCE_PARAM = "n"


class SteamAuthError(Exception):
    """The callback failed verification. Message is for logs, not clients."""


def build_login_url(*, return_to: str, realm: str) -> str:
    """The steamcommunity URL the browser is sent to.

    ``realm`` is what Steam shows the user as the requesting site and what
    the assertion is scoped to; ``return_to`` must live under it.
    """
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return f"{_STEAM_OPENID}?{urlencode(params)}"


def check_assertion(params: dict[str, str], *, expected_return_to: str, nonce: str | None) -> int:
    """The local half of verification — no network. Returns the claimed steamid64.

    Args:
        params: The ``openid.*`` parameters exactly as Steam sent them.
        expected_return_to: Our callback URL (scheme, host and path); a ``return_to``
            anywhere else means the assertion was minted for another site or app.
        nonce: The sign-in nonce from this browser's ``csmarket_oid`` cookie, or
            ``None`` when it sent none.

    Raises:
        SteamAuthError: A ``claimed_id`` that is not a Steam identity, a required field
            left unsigned, a foreign ``return_to``, or a missing or foreign nonce.
    """
    match = _CLAIMED_ID.match(params.get("openid.claimed_id", ""))
    if match is None:
        raise SteamAuthError("claimed_id is not a steam identity")
    signed = set(params.get("openid.signed", "").split(","))
    if not REQUIRED_SIGNED.issubset(signed):
        raise SteamAuthError("assertion leaves required fields unsigned")
    parts = urlsplit(params.get("openid.return_to", ""))
    if f"{parts.scheme}://{parts.netloc}{parts.path}" != expected_return_to:
        raise SteamAuthError("return_to does not belong to us")
    if not nonce:
        raise SteamAuthError("sign-in was not started in this browser")
    sent = parse_qs(parts.query).get(NONCE_PARAM, [])
    if len(sent) != 1 or not hmac.compare_digest(sent[0].encode(), nonce.encode()):
        raise SteamAuthError("sign-in nonce does not match this browser")
    return int(match.group(1))


async def verify_callback(
    params: dict[str, str],
    *,
    expected_return_to: str,
    nonce: str | None,
    http: httpx.AsyncClient | None = None,
) -> int:
    """Verify a Steam OpenID callback and return the steamid64.

    :func:`check_assertion` runs first, so nothing it refuses ever reaches Steam.

    Args:
        params: The ``openid.*`` query parameters exactly as Steam sent them.
        expected_return_to: Our own callback URL, without a query.
        nonce: This browser's sign-in nonce (the ``csmarket_oid`` cookie), if any.
        http: Injected client for tests.

    Raises:
        SteamAuthError: Any :func:`check_assertion` refusal, Steam saying the assertion
            is not valid, or Steam unreachable. The message never carries upstream text.
    """
    steam_id = check_assertion(params, expected_return_to=expected_return_to, nonce=nonce)
    check = {k: v for k, v in params.items() if k.startswith("openid.")}
    check["openid.mode"] = "check_authentication"

    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    try:
        resp = await client.post(
            _STEAM_OPENID,
            data=check,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.text
    except httpx.HTTPError as exc:
        # httpx messages can carry URLs and request data; only the type is kept (as
        # ``__cause__``, which the caller logs by class name).
        raise SteamAuthError("steam unreachable") from exc
    finally:
        if http is None:
            await client.aclose()

    if "is_valid:true" not in body:
        raise SteamAuthError("steam rejected the assertion")
    return steam_id


_SUMMARIES = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"


async def resolve_persona(
    steam_id: int,
    *,
    api_key: str,
    consumer: SteamApiConsumer,
    http: httpx.AsyncClient | None = None,
) -> tuple[str | None, str | None] | None:
    """``GetPlayerSummaries`` with Steam's "no such account" kept distinguishable.

    Args:
        steam_id: The 64-bit Steam id to summarise.
        api_key: Our Steam Web API key.
        consumer: Which feature spends the quota (``csmarket_steam_web_api_calls_total``).
            Required, so every call site names itself.
        http: Injected client for tests; otherwise one is built and closed here.

    Returns:
        ``None`` when Steam says no account holds this id (a 200 with an empty
        ``players`` list). Otherwise the ``(persona_name, avatar_url)`` pair; a pair of
        ``None``s means the account exists but gave us nothing to render.

    Raises:
        httpx.HTTPError: Transport failure, timeout, or a non-2xx response.
        ValueError: A 200 whose body is not JSON or not the expected shape.
    """
    client = http or httpx.AsyncClient(timeout=5.0)
    try:
        # Counts the call itself — the unit the daily quota is charged in — not the
        # parsing: a 200 we could not read still spent quota.
        with steam_web_api_call(endpoint="get_player_summaries", consumer=consumer):
            resp = await client.get(_SUMMARIES, params={"key": api_key, "steamids": str(steam_id)})
            resp.raise_for_status()
        # "Absent" is not "empty": only a ``players`` list that is really there and really
        # empty means "no such account". Any other shape is a degraded answer. The
        # isinstance guards keep a malformed body a ValueError — anything else (e.g.
        # AttributeError) would escape ``fetch_persona``'s catch and 500 a sign-in.
        body = resp.json()
        response = body.get("response") if isinstance(body, dict) else None
        if not isinstance(response, dict) or not isinstance(response.get("players"), list):
            raise ValueError("GetPlayerSummaries returned an unexpected shape")  # noqa: TRY004 -- upstream contract break, must stay a ValueError
        players = response["players"]
        if not players:
            return None
        player = players[0]
        if not isinstance(player, dict):
            raise ValueError("GetPlayerSummaries returned a non-object player")  # noqa: TRY004 -- upstream contract break, must stay a ValueError
        name = player.get("personaname")
        avatar = player.get("avatarfull") or player.get("avatarmedium")
        return (
            name if isinstance(name, str) and name else None,
            avatar if isinstance(avatar, str) and avatar else None,
        )
    finally:
        if http is None:
            await client.aclose()


_TRADE_HOLD = "https://api.steampowered.com/IEconService/GetTradeHoldDurations/v1/"


async def trade_hold_days(
    steam_id: int,
    token: str,
    *,
    api_key: str,
    consumer: SteamApiConsumer = "trade_link",
    http: httpx.AsyncClient | None = None,
) -> int | None:
    """Days Steam would hold a trade offer sent to this trade link.

    Non-zero means the account has had no mobile authenticator for 7 days: the offer
    would sit in escrow where either side can cancel it. The ``token`` is the trade
    link's access token — sent to Steam only, never logged.

    Args:
        steam_id: the recipient's steamid64.
        token: the trade link's ``token``.
        api_key: our Steam Web API key.
        consumer: which feature spends the quota (metrics label).
        http: injected client for tests.

    Returns:
        Whole days (rounded up); ``None`` when the body carries no number.

    Raises:
        httpx.HTTPError: transport failure, timeout or a non-2xx answer.
    """
    client = http or httpx.AsyncClient(timeout=4.0)
    try:
        with steam_web_api_call(endpoint="get_trade_hold_durations", consumer=consumer):
            resp = await client.get(
                _TRADE_HOLD,
                params={
                    "key": api_key,
                    "steamid_target": str(steam_id),
                    "trade_offer_access_token": token,
                },
            )
            resp.raise_for_status()
        body = resp.json()
        response = body.get("response") if isinstance(body, dict) else None
        escrow = response.get("their_escrow") if isinstance(response, dict) else None
        seconds = escrow.get("escrow_end_duration_seconds") if isinstance(escrow, dict) else None
        if not isinstance(seconds, int) or isinstance(seconds, bool):
            return None
        return -(-seconds // 86400)
    finally:
        if http is None:
            await client.aclose()


async def fetch_persona(
    steam_id: int,
    *,
    api_key: str,
    http: httpx.AsyncClient | None = None,
) -> tuple[str | None, str | None]:
    """The persona name and avatar for a steamid, best-effort.

    OpenID proves the identity but carries no profile, so this is the only source of a
    display name. Strictly cosmetic: any failure returns ``(None, None)`` and the
    sign-in proceeds nameless rather than broken; "no such account" is folded in on
    purpose, since OpenID has already proven the account exists. Counted under
    ``consumer="auth_signin"``. Callers that must tell those apart use
    :func:`resolve_persona`.
    """
    try:
        found = await resolve_persona(steam_id, api_key=api_key, consumer="auth_signin", http=http)
    except (httpx.HTTPError, ValueError):
        return None, None
    return found if found is not None else (None, None)


__all__ = [
    "NONCE_PARAM",
    "REQUIRED_SIGNED",
    "SteamAuthError",
    "build_login_url",
    "check_assertion",
    "fetch_persona",
    "resolve_persona",
    "trade_hold_days",
    "verify_callback",
]
