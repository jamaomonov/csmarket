#!/usr/bin/env python3
"""The per-module coverage gate (AGENTS §9): each of ``orders``, ``payments``, ``wallet`` and
``skins`` (the money path) and, since M4b, ``notifications`` and ``realtime`` must keep
≥ 95 % line coverage on its own.

Reads the ``coverage json`` report that ``make test-py`` and CI ``test-py`` write
(``coverage.json`` by default) and sums covered lines over statements per module, i.e.
every file under ``csmarket/modules/<module>/``. The global 80 % floor stays with
``fail_under`` in ``pyproject.toml``; this gate catches a drop where it happens.

Usage: ``python scripts/check-module-coverage.py [coverage.json]``.
Exit codes: 0 every module at or above the line, 1 a module below it, 2 the report is
missing, unreadable, or has no file of a module (a gate that measured nothing must not
pass).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: The gated modules (the money path, then M4b's letters and live updates) and their line.
MODULES = (
    "orders",
    "payments",
    "wallet",
    "skins",
    "notifications",
    "realtime",
    "skinslink",
    "lisskins",
)
THRESHOLD = 95.0


def _totals(files: dict[str, dict[str, dict[str, int]]], module: str) -> tuple[int, int]:
    """Covered lines and statements over every file of ``module``."""
    marker = f"csmarket/modules/{module}/"
    covered = statements = 0
    for path, report in files.items():
        if marker in path.replace("\\", "/"):
            covered += int(report["summary"]["covered_lines"])
            statements += int(report["summary"]["num_statements"])
    return covered, statements


def main(argv: list[str]) -> int:
    """Print each module's coverage; the exit code says whether the gate holds."""
    report_path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    try:
        files = json.loads(report_path.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"check-module-coverage: cannot read {report_path}: {exc}", file=sys.stderr)
        return 2
    failed = False
    for module in MODULES:
        covered, statements = _totals(files, module)
        if statements == 0:
            print(f"check-module-coverage: no file of {module} in {report_path}", file=sys.stderr)
            return 2
        percent = 100.0 * covered / statements
        ok = percent >= THRESHOLD
        failed = failed or not ok
        mark = "ok" if ok else f"BELOW {THRESHOLD:.0f} %"
        print(f"{module:<9} {percent:6.2f} %  ({covered}/{statements})  {mark}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
