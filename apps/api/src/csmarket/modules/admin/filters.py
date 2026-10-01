"""Query-string filters shared by the admin list routes (users, payments, audit)."""

from __future__ import annotations

from typing import Any

from fastapi import Query

#: No NUL byte anywhere: asyncpg refuses ``\x00`` in a text parameter, which would surface
#: as a 500; the pattern turns it into a 422 before the query runs.
_NO_NUL = r"^[^\x00]*$"


def text_filter(max_length: int) -> Any:  # Any: FastAPI's ``Query()`` is typed ``Any``
    """A free-text filter: at most ``max_length`` characters and no NUL byte, else 422.

    Args:
        max_length: The longest value accepted.

    Returns:
        The ``Query`` marker to put in the parameter's ``Annotated``.
    """
    return Query(max_length=max_length, pattern=_NO_NUL)


__all__ = ["text_filter"]
