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
        "csmarket.modules.auth.deps",
        "csmarket.modules.auth.routes",
        "csmarket.modules.auth.api",
        "csmarket.modules.users.api",
        "csmarket.modules.users.routes",
        "csmarket.modules.users.tradelink",
        "csmarket.modules.skins.api",
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
