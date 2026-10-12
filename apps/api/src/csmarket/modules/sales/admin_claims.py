"""«Беру в работу»: one admin claims a card payout while the money is being sent (admin
review 2026-10-12 H1).

The claim is a lease on the request (``claimed_by`` / ``claimed_at``), live for :data:`TTL`.
While it is live, another admin can neither reveal the number nor decide the request (409
``payout_claimed``) unless they take it over explicitly (``takeover``, audited
``sales.payout.takeover``). A reveal claims a free request for its admin on the way, so the
number never reaches two people unnoticed. A decision («Выплачено», «Отклонить»,
«Отменить (откат)») releases the claim; so does the claimer's «Отпустить» and the clock.

Every change is audited in the caller's transaction; flush, never commit.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.modules.admin.api import record
from csmarket.modules.sales.models import PayoutRequest

#: How long «Беру в работу» holds a request without a renewal.
TTL = timedelta(minutes=15)


def claim_until(request: PayoutRequest, at: datetime | None = None) -> datetime | None:
    """When the live claim ends; ``None`` when nobody holds the request."""
    if request.claimed_by is None or request.claimed_at is None:
        return None
    until = request.claimed_at + TTL
    return until if until > (at or now()) else None


def held_by_other(request: PayoutRequest, admin_id: str) -> bool:
    """Another admin holds a live claim on the request."""
    return claim_until(request) is not None and request.claimed_by != admin_id


def _claimed() -> ConflictError:
    return ConflictError(
        "another admin is paying this request; take it over first", code="payout_claimed"
    )


def ensure_free_for(request: PayoutRequest, admin_id: str) -> None:
    """Refuse when another admin holds a live claim.

    Raises:
        ConflictError: ``payout_claimed``.
    """
    if held_by_other(request, admin_id):
        raise _claimed()


async def take(
    db: AsyncSession, request: PayoutRequest, *, admin_id: str, takeover: bool = False
) -> bool:
    """Claim (or renew) ``request`` for ``admin_id``; the caller holds the request's lock.

    Returns:
        Whether a new claim started (a renewal of one's own live claim is not audited).

    Raises:
        ConflictError: ``payout_claimed`` — another admin's live claim and no ``takeover``.
    """
    previous = request.claimed_by if claim_until(request) is not None else None
    if previous is not None and previous != admin_id and not takeover:
        raise _claimed()
    fresh = previous != admin_id
    request.claimed_by, request.claimed_at = admin_id, now()
    if fresh:
        await record(
            db,
            actor_id=admin_id,
            action="sales.payout.takeover" if previous else "sales.payout.claim",
            target_type="payout_request",
            target_id=request.id,
            payload={"from": previous} if previous else {},
        )
    await db.flush()
    return fresh


async def release(db: AsyncSession, request: PayoutRequest, *, admin_id: str) -> bool:
    """«Отпустить»: the claimer gives the request back. Nobody's claim is a no-op.

    Returns:
        Whether a claim was released.

    Raises:
        ConflictError: ``payout_claimed`` — another admin holds it.
    """
    if claim_until(request) is None:
        clear(request)
        await db.flush()
        return False
    ensure_free_for(request, admin_id)
    clear(request)
    await record(
        db,
        actor_id=admin_id,
        action="sales.payout.release",
        target_type="payout_request",
        target_id=request.id,
        payload={},
    )
    await db.flush()
    return True


def clear(request: PayoutRequest) -> None:
    """Drop the claim (a decision was made, or the claimer let go)."""
    request.claimed_by, request.claimed_at = None, None


__all__ = ["TTL", "claim_until", "clear", "ensure_free_for", "held_by_other", "release", "take"]
