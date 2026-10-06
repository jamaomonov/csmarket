"""Email templates: every letter in ru / uz / en, escaped, with its link (M4b T4)."""

from __future__ import annotations

import pytest
from csmarket.modules.notifications.templates import Links, render

LINKS = Links(
    order_url="https://csmarket.test/en/orders/AB12CD34",
    balance_url="https://csmarket.test/en/account/transactions",
    confirm_url="https://csmarket.test/en/account/email/confirm?token=tok.en",
)
NUMBER = "AB12CD34"
PAYLOADS = {
    "receipt": {"number": NUMBER, "skin": "AK-47 | Redline (Field-Tested)"},
    "trade_sent": {"number": NUMBER, "skin": "AK-47", "send_until": "2026-10-02T13:30:00+00:00"},
    "refunded": {"number": NUMBER, "skin": "AK-47", "amount_uzs": "1250000"},
    "verify": {"token": "tok.en"},
}
LINK_OF = {
    "receipt": LINKS.order_url,
    "trade_sent": LINKS.order_url,
    "refunded": LINKS.balance_url,
    "verify": LINKS.confirm_url,
}
#: Never in a letter: a trade link, a Steam ID, the buyer's balance.
FORBIDDEN = ("steamcommunity.com", "tradeoffer", "partner=", "7656119")


@pytest.mark.parametrize("locale", ["ru", "uz", "en"])
@pytest.mark.parametrize("kind", ["receipt", "trade_sent", "refunded", "verify"])
def test_every_letter_renders_in_every_locale(kind: str, locale: str) -> None:
    number = None if kind == "verify" else NUMBER
    letter = render(kind, locale=locale, number=number, payload=PAYLOADS[kind], links=LINKS)  # type: ignore[arg-type]
    assert letter.subject
    assert letter.html.startswith("<!DOCTYPE html>")
    assert LINK_OF[kind] in letter.text
    assert LINK_OF[kind].replace("&", "&amp;") in letter.html
    if number:
        assert number in letter.subject
        assert number in letter.text
    for leak in FORBIDDEN:
        assert leak not in letter.html + letter.text
    assert "<img" not in letter.html  # no tracking pixel, no remote image
    assert "fonts.googleapis" not in letter.html


def test_the_copy_is_the_owners() -> None:
    receipt = render(
        "receipt", locale="ru", number=NUMBER, payload=PAYLOADS["receipt"], links=LINKS
    )
    assert receipt.subject == f"Заказ #{NUMBER} оплачен"
    assert "Оплата получена. Покупаем AK-47 | Redline (Field-Tested)" in receipt.text
    refunded = render(
        "refunded", locale="ru", number=NUMBER, payload=PAYLOADS["refunded"], links=LINKS
    )
    assert refunded.subject == f"Деньги по заказу #{NUMBER} на балансе"
    assert "1 250 000 сум вернулись на баланс csmarket." in refunded.text
    assert "Открыть баланс" in refunded.html
    verify = render("verify", locale="ru", number=None, payload=PAYLOADS["verify"], links=LINKS)
    assert verify.subject == "Подтвердите почту"
    assert "Ссылка действует 24 часа." in verify.text


def test_uzbek_uses_the_modifier_letters() -> None:
    letter = render("receipt", locale="uz", number=NUMBER, payload=PAYLOADS["receipt"], links=LINKS)
    assert "ʻ" in letter.subject + letter.text  # U+02BB
    assert "'" not in letter.subject
    assert "‘" not in letter.text + letter.subject


def test_the_deadline_is_in_tashkent_time() -> None:
    letter = render(
        "trade_sent", locale="ru", number=NUMBER, payload=PAYLOADS["trade_sent"], links=LINKS
    )
    assert "до 02.10.2026 18:30 по Ташкенту" in letter.text


def test_without_a_deadline_the_letter_still_asks_to_accept() -> None:
    payload = {"number": NUMBER, "skin": "AK-47"}
    letter = render("trade_sent", locale="en", number=NUMBER, payload=payload, links=LINKS)
    assert "Accept it in Steam." in letter.text


def test_a_skin_name_is_escaped_in_html() -> None:
    payload = {"number": NUMBER, "skin": "<script>alert(1)</script>"}
    letter = render("receipt", locale="en", number=NUMBER, payload=payload, links=LINKS)
    assert "<script>" not in letter.html
    assert "&lt;script&gt;" in letter.html
    assert "<script>alert(1)</script>" in letter.text


def test_english_amounts_use_the_iso_code() -> None:
    letter = render(
        "refunded", locale="en", number=NUMBER, payload=PAYLOADS["refunded"], links=LINKS
    )
    assert "1,250,000 UZS" in letter.text


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="kind"):
        render("marketing", locale="ru", number=None, payload={}, links=LINKS)
