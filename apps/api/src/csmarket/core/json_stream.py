"""Read a huge ``{…, "items": [ … ], …}`` JSON body without holding it in memory.

Skinslink's full sale list (~500k items, ~200 MB) and LIS-SKINS' price export (~2.4 M lots,
~855 MB) are each one JSON object; parsed whole neither fits the scheduler's memory. :class:`ItemsScanner` is fed the body
in text chunks and hands back each element of ``data.items`` as soon as it is complete; what
precedes and follows the array (``success``, ``last_update_at``) is kept as text and read
once the stream ends.
"""

from __future__ import annotations

import json
import re
from typing import Any

_ITEMS = re.compile(r'"items"\s*:\s*\[')
#: Skinslink's envelope: ``{"success": true, "data": {…, "last_update_at": "…"}}``.
SUCCESS_TRUE = re.compile(r'"success"\s*:\s*true')
LAST_UPDATE_AT = re.compile(r'"last_update_at"\s*:\s*"([^"]*)"')
_TOTAL_PAGES = re.compile(r'"total_pages"\s*:\s*([0-9]+)')
_SKIP = " \t\r\n,"
#: The head before ``"items": [`` is a few short fields; more means it is not this body.
_MAX_HEAD = 64 * 1024
_DECODER = json.JSONDecoder()


class ItemsScanner:
    """Incremental reader of one JSON object whose ``"items": [ … ]`` array is huge.

    Args:
        success: Must match the text around the array once the body ended
            (Skinslink: :data:`SUCCESS_TRUE`; LIS-SKINS: ``"status": "success"``).
        cursor: Its group 1 is what :meth:`finish` returns
            (Skinslink: :data:`LAST_UPDATE_AT`; LIS-SKINS: ``last_update``).
    """

    def __init__(
        self, *, success: re.Pattern[str] = SUCCESS_TRUE, cursor: re.Pattern[str] = LAST_UPDATE_AT
    ) -> None:
        self._buf = ""
        self._head = ""
        self._tail = ""
        self._state = "head"
        self._success = success
        self._cursor = cursor

    # Any: one raw item object, validated by the caller (``client._item``).
    def feed(self, text: str) -> list[Any]:
        """Add ``text``; return the items it completed, in order.

        Raises:
            ValueError: No ``items`` array where one must be (not this body).
        """
        self._buf += text
        found: list[Any] = []
        if self._state == "head":
            match = _ITEMS.search(self._buf)
            if match is None:
                if len(self._buf) > _MAX_HEAD:
                    raise ValueError("no items array")
                return found
            self._head, self._buf = self._buf[: match.start()], self._buf[match.end() :]
            self._state = "items"
        if self._state == "items":
            found = self._items()
        if self._state == "tail":
            self._tail += self._buf
            self._buf = ""
        return found

    def _items(self) -> list[Any]:
        found: list[Any] = []
        buf, pos = self._buf, 0
        while True:
            while pos < len(buf) and buf[pos] in _SKIP:
                pos += 1
            if pos >= len(buf):
                break
            if buf[pos] == "]":
                self._state, pos = "tail", pos + 1
                break
            try:
                obj, pos = _DECODER.raw_decode(buf, pos)
            except json.JSONDecodeError:
                break  # an item cut by the chunk: wait for the rest
            found.append(obj)
        self._buf = buf[pos:]
        return found

    @property
    def total_pages(self) -> int | None:
        """``total_pages`` of a paginated answer (it precedes the items), else ``None``."""
        match = _TOTAL_PAGES.search(self._head) or _TOTAL_PAGES.search(self._tail)
        return int(match.group(1)) if match else None

    @property
    def headless(self) -> str | None:
        """The whole body when it never reached an ``items`` array (an error answer)."""
        return self._buf if self._state == "head" else None

    def finish(self) -> str | None:
        """The ``last_update_at`` cursor once the whole body was fed.

        Raises:
            ValueError: The body ended inside the array, or did not say ``success: true``.
        """
        if self._state != "tail":
            raise ValueError("truncated body")
        if not self._success.search(self._head + self._tail):
            raise ValueError("not a success")
        match = self._cursor.search(self._tail) or self._cursor.search(self._head)
        return match.group(1) if match else None


__all__ = ["LAST_UPDATE_AT", "SUCCESS_TRUE", "ItemsScanner"]
