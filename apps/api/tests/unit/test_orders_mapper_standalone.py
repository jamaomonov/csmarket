"""The Order mapper resolves in every process (``orders.api_key_id`` -> ``api_keys``)."""

from __future__ import annotations

import subprocess
import sys

import pytest

_CHECK = (
    "import {mod}\n"
    "from sqlalchemy.orm import class_mapper\n"
    "from csmarket.modules.orders.models import Order\n"
    "class_mapper(Order)._sorted_tables\n"
    "print('ok')\n"
)


@pytest.mark.parametrize("module", ["csmarket_worker.consumer", "csmarket.main"])
def test_order_mapper_resolves_with_only_one_entrypoint_imported(module: str) -> None:
    out = subprocess.run(
        [sys.executable, "-c", _CHECK.format(mod=module)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-1500:]
    assert out.stdout.strip() == "ok"
