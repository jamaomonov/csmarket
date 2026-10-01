"""Any module can be imported first, in a fresh interpreter, without a circular import.

``api/v1/deps.py`` is imported by module routes and dependencies; the router that mounts
those modules must therefore not live in the ``csmarket.api.v1`` package ``__init__``,
or importing a module's ``deps``/``routes`` before the app closes a cycle back to it.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "csmarket.modules.admin.api",
        "csmarket.modules.admin.audit",
        "csmarket.modules.admin.audit_routes",
        "csmarket.modules.admin.audit_schemas",
        "csmarket.modules.admin.audit_service",
        "csmarket.modules.admin.deps",
        "csmarket.modules.admin.payments_kassa",
        "csmarket.modules.admin.payments_routes",
        "csmarket.modules.admin.payments_schemas",
        "csmarket.modules.admin.payments_service",
        "csmarket.modules.admin.routes",
        "csmarket.modules.admin.users_routes",
        "csmarket.modules.admin.users_schemas",
        "csmarket.modules.admin.users_service",
        "csmarket.modules.auth.deps",
        "csmarket.modules.auth.routes",
        "csmarket.modules.auth.api",
        "csmarket.modules.click.api",
        "csmarket.modules.click.errors",
        "csmarket.modules.click.models",
        "csmarket.modules.click.routes",
        "csmarket.modules.click.service",
        "csmarket.modules.click.signature",
        "csmarket.modules.payme.api",
        "csmarket.modules.payme.errors",
        "csmarket.modules.payme.models",
        "csmarket.modules.payme.routes",
        "csmarket.modules.payme.service",
        "csmarket.modules.users.api",
        "csmarket.modules.users.routes",
        "csmarket.modules.users.tradelink",
        "csmarket.modules.uzum.api",
        "csmarket.modules.uzum.errors",
        "csmarket.modules.uzum.models",
        "csmarket.modules.uzum.routes",
        "csmarket.modules.uzum.service",
        "csmarket.modules.payments.api",
        "csmarket.modules.payments.dev_routes",
        "csmarket.modules.payments.external_ids",
        "csmarket.modules.payments.fsm",
        "csmarket.modules.payments.gateways",
        "csmarket.modules.payments.gateways.base",
        "csmarket.modules.payments.gateways.click",
        "csmarket.modules.payments.gateways.mock",
        "csmarket.modules.payments.gateways.payme",
        "csmarket.modules.payments.gateways.uzum",
        "csmarket.modules.payments.hooks",
        "csmarket.modules.payments.models",
        "csmarket.modules.payments.payable",
        "csmarket.modules.payments.routes",
        "csmarket.modules.payments.schemas",
        "csmarket.modules.payments.topups",
        "csmarket.modules.skins.admin_routes",
        "csmarket.modules.skins.api",
        "csmarket.modules.skins.routes",
        "csmarket.modules.skins.seo_routes",
        "csmarket.modules.skins.service",
        "csmarket.modules.wallet.adjust",
        "csmarket.modules.wallet.api",
        "csmarket.modules.wallet.entries",
        "csmarket.modules.wallet.models",
        "csmarket.modules.wallet.routes",
        "csmarket.modules.wallet.schemas",
        "csmarket.modules.wallet.service",
        "csmarket.api.v1.deps",
        "csmarket.api.v1.router",
        "csmarket.bootstrap",
    ],
)
def test_module_imports_first_without_a_cycle(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_wallet_never_imports_payments() -> None:
    """One direction only: ``payments`` builds on ``wallet``, never the reverse."""
    code = (
        "import sys, csmarket.modules.wallet.api, csmarket.modules.wallet.service, "
        "csmarket.modules.wallet.routes; "
        "sys.exit(any(m.startswith('csmarket.modules.payments') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr or "wallet imported payments"


def test_no_domain_module_imports_the_admin_users_routes() -> None:
    """One direction only: ``admin`` builds on ``users``, ``wallet``, ``payments``, ``auth``."""
    code = (
        "import sys, csmarket.modules.users.api, csmarket.modules.users.routes, "
        "csmarket.modules.wallet.api, csmarket.modules.wallet.routes, "
        "csmarket.modules.payments.api, csmarket.modules.payments.routes, "
        "csmarket.modules.auth.api; "
        "sys.exit(any(m.startswith('csmarket.modules.admin.users') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr or "a domain module imported admin.users_*"


def test_no_domain_module_imports_the_admin_payments_or_audit_readers() -> None:
    """One direction only: ``admin`` reads ``click``, ``payme``, ``uzum`` and ``payments``."""
    code = (
        "import sys, csmarket.modules.click.api, csmarket.modules.click.routes, "
        "csmarket.modules.payme.api, csmarket.modules.payme.routes, "
        "csmarket.modules.uzum.api, csmarket.modules.uzum.routes, "
        "csmarket.modules.payments.api, csmarket.modules.payments.routes, "
        "csmarket.modules.payments.dev_routes, csmarket.modules.wallet.routes, "
        "csmarket.modules.users.routes, csmarket.modules.skins.admin_routes; "
        "sys.exit(any(m.startswith(('csmarket.modules.admin.payments', "
        "'csmarket.modules.admin.audit_')) for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr or "a domain module imported an admin reader"
