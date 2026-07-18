"""M4.6 gate: "a static-typing negative check proving each view omits the
type methods and the wrong-type modifiers (e.g. a `type: ignore[attr-defined]`
round-trip on `.real(0,1).bool()` and `.categorical(...).log_scale()`)"
(IMPLEMENTATION_PLAN.md).

Runs `mypy --strict` over `src/` together with the fixture in one
invocation — a standalone file has no `py.typed` marker for mypy to resolve
`designspace`'s real types against (it would see everything as `Any` and
never flag `attr-defined`), so it must be checked in the same run as the
source tree, exactly as `uv run mypy --strict src/` already does in CI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = Path(__file__).parent / "_row2_and_wrong_type_modifier.py"


def test_row2_and_wrong_type_modifier_ignores_are_load_bearing() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "src", str(_FIXTURE)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
