"""The money modules' per-module coverage gate (AGENTS §9, ``scripts/check-module-coverage.py``)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "check-module-coverage.py"
MODULES = ("orders", "payments", "wallet", "skins", "notifications", "realtime")


def _report(tmp_path: Path, percents: dict[str, tuple[int, int]]) -> Path:
    """A ``coverage json`` report with two files per module splitting ``(covered, total)``."""
    files: dict[str, object] = {}
    for module, (covered, total) in percents.items():
        half = total // 2
        for name, (c, t) in {
            "a.py": (min(covered, half), half),
            "b.py": (covered - min(covered, half), total - half),
        }.items():
            source = f"apps/api/src/csmarket/modules/{module}/{name}"
            files[source] = {"summary": {"covered_lines": c, "num_statements": t}}
    files["apps/api/src/csmarket/core/config.py"] = {
        "summary": {"covered_lines": 0, "num_statements": 50}
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"files": files}), encoding="utf-8")
    return path


def _run(report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(report)], capture_output=True, text=True, check=False
    )


def test_every_module_at_the_line_passes(tmp_path: Path) -> None:
    result = _run(_report(tmp_path, dict.fromkeys(MODULES, (95, 100))))
    assert result.returncode == 0, result.stdout + result.stderr
    for module in MODULES:
        assert module in result.stdout


@pytest.mark.parametrize("module", MODULES)
def test_one_module_below_the_line_fails_and_is_named(tmp_path: Path, module: str) -> None:
    percents = dict.fromkeys(MODULES, (99, 100))
    percents[module] = (949, 1000)  # 94.9 %: the global floor would never notice
    result = _run(_report(tmp_path, percents))
    assert result.returncode == 1
    (line,) = [ln for ln in result.stdout.splitlines() if "BELOW" in ln]
    assert line.startswith(module)


def test_a_module_missing_from_the_report_is_a_guard_failure(tmp_path: Path) -> None:
    percents = dict.fromkeys(
        ("orders", "payments", "wallet", "notifications", "realtime"), (100, 100)
    )
    result = _run(_report(tmp_path, percents))
    assert result.returncode == 2
    assert "skins" in result.stderr


def test_a_missing_report_is_a_guard_failure(tmp_path: Path) -> None:
    result = _run(tmp_path / "nope.json")
    assert result.returncode == 2
