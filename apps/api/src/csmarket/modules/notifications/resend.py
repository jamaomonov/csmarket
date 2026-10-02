"""Resend (https://resend.com): one ``POST /emails`` per letter (M4b, decision D5).

The outbox row id travels as ``Idempotency-Key``, so a retried send after a lost answer is
one letter, not two. Errors split by what a retry can fix: :class:`EmailRetryableError`
(network, timeout, 429, 5xx, no key yet) and :class:`EmailRejectedError` (any other 4xx —
a bad address does not get better). Log lines carry the outcome and the HTTP status only:
never the key, the recipient or the provider's message text.
"""

from __future__ import annotations

import httpx

from csmarket.core.logging import get_logger

log = get_logger("csmarket.notifications.resend")


class EmailSendError(Exception):
    """A send that did not go through. ``code`` is a short, PII-free reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EmailRetryableError(EmailSendError):
    """Worth another attempt later: network, timeout, 429, 5xx, a missing key."""


class EmailRejectedError(EmailSendError):
    """Refused for good (a 4xx other than 429): the row fails at once."""


class ResendClient:
    """Sends one letter through Resend's REST API."""

    def __init__(self, api_key: str, base_url: str, timeout: float, *, sender: str) -> None:
        """Bind the key, the API root, the per-call timeout and the ``From`` header."""
        self._key = api_key
        self._url = base_url.rstrip("/") + "/emails"
        self._timeout = timeout
        self._sender = sender

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        idempotency_key: str,
        user_id: str = "",  # noqa: ARG002 -- the dev transport files letters by it
        kind: str = "",  # noqa: ARG002 -- as above
    ) -> str:
        """Send one letter; return Resend's message id.

        Raises:
            EmailRetryableError: Network failure, timeout, 429, 5xx, no key, no id.
            EmailRejectedError: Any other 4xx.
        """
        if not self._key:
            raise EmailRetryableError("no_key")
        body = {"from": self._sender, "to": [to], "subject": subject, "html": html, "text": text}
        headers = {"Authorization": f"Bearer {self._key}", "Idempotency-Key": idempotency_key}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException:
            log.warning("notifications.resend.call", outcome="timeout")
            raise EmailRetryableError("timeout") from None
        except httpx.HTTPError:
            log.warning("notifications.resend.call", outcome="network")
            raise EmailRetryableError("network") from None
        return _message_id(resp)


def _message_id(resp: httpx.Response) -> str:
    """Resend's id from a 2xx answer, or the error the status calls for."""
    status = resp.status_code
    if status == 429 or status >= 500:
        log.warning("notifications.resend.call", outcome="retryable", status=status)
        raise EmailRetryableError(f"http_{status}")
    if status >= 300:
        log.warning("notifications.resend.call", outcome="rejected", status=status)
        raise EmailRejectedError(f"http_{status}")
    try:
        message_id = resp.json().get("id")
    except ValueError:
        message_id = None
    if not isinstance(message_id, str) or not message_id:
        log.warning("notifications.resend.call", outcome="no_id", status=status)
        raise EmailRetryableError("no_id")
    log.info("notifications.resend.call", outcome="sent", status=status)
    return message_id[:64]
