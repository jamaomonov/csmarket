"""Public interface of the ``wallet`` module — other modules import from here only.

``wallet`` never imports ``payments``: ``payments`` (and M4 ``orders``, and ``admin``) build
on it. ``api``/``service`` are domain-pure; only ``wallet.routes`` reaches ``auth.api`` and
``users.models`` for the signed-in customer.
"""

from __future__ import annotations

from csmarket.modules.wallet.adjust import ADMIN_ADJUST_MAX, admin_adjust
from csmarket.modules.wallet.entries import (
    AdminEntry,
    EntriesPage,
    Entry,
    entries_for_admin,
    entries_for_user,
    user_balance_column,
)
from csmarket.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction
from csmarket.modules.wallet.purchases import WALLET, credit_order_refund, debit_purchase
from csmarket.modules.wallet.sales import credit_payout_return, credit_sale
from csmarket.modules.wallet.service import (
    NORMAL_SIDE,
    TX_KINDS,
    Direction,
    InsufficientBalanceError,
    Leg,
    Reference,
    balance,
    credit_topup,
    ensure_account,
    post,
    reverse_topup,
    user_account,
    user_balance,
)

__all__ = [
    "ADMIN_ADJUST_MAX",
    "NORMAL_SIDE",
    "TX_KINDS",
    "WALLET",
    "AdminEntry",
    "Direction",
    "EntriesPage",
    "Entry",
    "InsufficientBalanceError",
    "Leg",
    "Reference",
    "WalletAccount",
    "WalletPosting",
    "WalletTransaction",
    "admin_adjust",
    "balance",
    "credit_order_refund",
    "credit_payout_return",
    "credit_sale",
    "credit_topup",
    "debit_purchase",
    "ensure_account",
    "entries_for_admin",
    "entries_for_user",
    "post",
    "reverse_topup",
    "user_account",
    "user_balance",
    "user_balance_column",
]
