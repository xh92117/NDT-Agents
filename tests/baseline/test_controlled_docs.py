"""Exercise the controlled-document checker as part of the normal test suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_controlled_document_checker_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_controlled_docs.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DOC=PASS" in result.stdout
