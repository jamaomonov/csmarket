"""Payme Merchant API error catalogue.

Payme's Merchant API is JSON-RPC 2.0: every failure is answered HTTP 200 with
``{"error": {"code": <int>, "message": {"ru", "uz", "en"}, "data": <field|null>}, "id": ...}``.
This module is pure: it builds :class:`PaymeError` instances with the code Payme's spec
assigns, the trilingual message Payme shows on its checkout, and the offending field
(``data``) — ``"order"``, the account field, for the account-range codes (−31050..−31099).
"""

from __future__ import annotations

#: The account field Payme sends (``params.account.order``), named in account-range errors.
ACCOUNT_FIELD = "order"

#: A rendered JSON-RPC error object: ``code``, ``message`` and ``data``.
RpcError = dict[str, int | dict[str, str] | str | None]


class PaymeError(Exception):
    """A Payme Merchant API error, raised by a handler and rendered on the wire.

    Attributes:
        code: The JSON-RPC error code Payme's spec assigns to this failure.
        message: Trilingual message keyed ``ru``, ``uz``, ``en``.
        data: The offending request field, or ``None``.
        persist: Whether the route commits what the handler wrote before refusing (a
            transaction cancelled while refusing a second charge); otherwise it rolls back.
    """

    def __init__(
        self,
        code: int,
        message: dict[str, str],
        data: str | None = None,
        *,
        persist: bool = False,
    ) -> None:
        """Initialise the error.

        Args:
            code: The JSON-RPC error code.
            message: Trilingual message with keys ``ru``, ``uz``, ``en``.
            data: The offending field name, or ``None``.
            persist: Commit the handler's writes instead of rolling them back.
        """
        super().__init__(message.get("en", str(code)))
        self.code = code
        self.message = message
        self.data = data
        self.persist = persist

    def to_rpc_error(self) -> RpcError:
        """The JSON-RPC ``error`` object: ``{"code", "message", "data"}``."""
        return {"code": self.code, "message": self.message, "data": self.data}


def invalid_amount() -> PaymeError:
    """−31001: the amount (tiyin) is not the top-up's amount × 100."""
    return PaymeError(
        -31001, {"ru": "Неверная сумма", "uz": "Notoʻgʻri summa", "en": "Invalid amount"}
    )


def transaction_not_found() -> PaymeError:
    """−31003: no transaction with this Payme id."""
    return PaymeError(
        -31003,
        {
            "ru": "Транзакция не найдена",
            "uz": "Tranzaksiya topilmadi",
            "en": "Transaction not found",
        },
    )


def cannot_cancel_spent() -> PaymeError:
    """−31007: the performed payment cannot be cancelled (ruling R7) — a top-up whose money
    is no longer on the balance, or an order (its skin is bought at payment)."""
    return PaymeError(
        -31007,
        {
            "ru": "Услуга оказана. Невозможно отменить транзакцию",
            "uz": "Xizmat koʻrsatildi. Tranzaksiyani bekor qilib boʻlmaydi",
            "en": "Service already provided. Cannot cancel transaction",
        },
    )


def operation_not_permitted(*, persist: bool = False) -> PaymeError:
    """−31008: not permitted in the transaction's state (or a second charge refused)."""
    return PaymeError(
        -31008,
        {
            "ru": "Невозможно выполнить операцию",
            "uz": "Amalni bajarib boʻlmaydi",
            "en": "Operation not permitted",
        },
        persist=persist,
    )


def account_not_found() -> PaymeError:
    """−31050: ``account.order`` is missing or names nothing."""
    return PaymeError(
        -31050,
        {"ru": "Заказ не найден", "uz": "Buyurtma topilmadi", "en": "Order not found"},
        data=ACCOUNT_FIELD,
    )


def account_not_payable(*, persist: bool = False) -> PaymeError:
    """−31051: already paid, expired or reversed (or an order cancelled before Perform)."""
    return PaymeError(
        -31051,
        {
            "ru": "Заказ недоступен к оплате или уже оплачен",
            "uz": "Buyurtma toʻlovga yaroqsiz yoki allaqachon toʻlangan",
            "en": "Order is not payable or already paid",
        },
        data=ACCOUNT_FIELD,
        persist=persist,
    )


def account_busy() -> PaymeError:
    """−31099: another active Payme transaction already holds this top-up or order.

    Payme's sandbox asserts an account-range code (−31050..−31099), not −31008, for a
    second, different ``CreateTransaction`` on a busy account.
    """
    return PaymeError(
        -31099,
        {
            "ru": "Заказ уже обрабатывается другой транзакцией",
            "uz": "Buyurtma boshqa tranzaksiya tomonidan qayta ishlanmoqda",
            "en": "Order is already being processed by another transaction",
        },
        data=ACCOUNT_FIELD,
    )


def unauthorized() -> PaymeError:
    """−32504: the Basic-auth credentials are not Payme's."""
    return PaymeError(
        -32504,
        {
            "ru": "Недостаточно привилегий для выполнения метода",
            "uz": "Metodni bajarish uchun huquqlar yetarli emas",
            "en": "Insufficient privileges to perform this method",
        },
    )


def method_not_post() -> PaymeError:
    """−32300: the request was not an HTTP POST."""
    return PaymeError(
        -32300,
        {
            "ru": "Метод не поддерживается",
            "uz": "Metod qoʻllab-quvvatlanmaydi",
            "en": "Method not supported",
        },
    )


def bad_json() -> PaymeError:
    """−32700: the body is not JSON."""
    return PaymeError(
        -32700,
        {
            "ru": "Ошибка при разборе JSON",
            "uz": "JSON tahlilida xatolik",
            "en": "Error parsing JSON",
        },
    )


def bad_rpc_fields() -> PaymeError:
    """−32600: the envelope or a required parameter is missing or mistyped."""
    return PaymeError(
        -32600, {"ru": "Неверный запрос", "uz": "Notoʻgʻri soʻrov", "en": "Invalid request"}
    )


def method_not_found() -> PaymeError:
    """−32601: a ``method`` we do not implement."""
    return PaymeError(
        -32601, {"ru": "Метод не найден", "uz": "Metod topilmadi", "en": "Method not found"}
    )


def internal_error() -> PaymeError:
    """−32400: an unexpected failure, including a failed commit."""
    return PaymeError(
        -32400,
        {
            "ru": "Внутренняя ошибка сервера",
            "uz": "Server ichki xatosi",
            "en": "Internal server error",
        },
    )


def fiscal_receipt_not_found() -> PaymeError:
    """−32001: ``SetFiscalData`` for an unknown transaction."""
    return PaymeError(
        -32001,
        {
            "ru": "Фискальный чек не найден",
            "uz": "Fiskal chek topilmadi",
            "en": "Fiscal receipt not found",
        },
    )


__all__ = [
    "ACCOUNT_FIELD",
    "PaymeError",
    "RpcError",
    "account_busy",
    "account_not_found",
    "account_not_payable",
    "bad_json",
    "bad_rpc_fields",
    "cannot_cancel_spent",
    "fiscal_receipt_not_found",
    "internal_error",
    "invalid_amount",
    "method_not_found",
    "method_not_post",
    "operation_not_permitted",
    "transaction_not_found",
    "unauthorized",
]
