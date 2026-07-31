"""Every file under `examples/` must run to completion. Nothing else
exercises them — CLAUDE.md's commit gates only type-check `src/` — so this
is what catches an example rotting after a milestone changes the surface it
demonstrates. Glob-driven: a new example is covered the moment it lands.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize(
    "path", sorted(EXAMPLES_DIR.glob("*.py")), ids=lambda p: p.stem
)
def test_example_runs(path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
