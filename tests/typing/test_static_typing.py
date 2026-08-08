"""A static-typing negative check over the builder views.

Each view must omit the type methods and the wrong-type modifiers, so that
`.real(0, 1).bool()` and `.categorical(...).log_scale()` are both
`attr-defined` errors.

`mypy --strict` runs over `src/` together with the fixture in one
invocation. A standalone file has no `py.typed` marker for mypy to resolve
`designspace`'s real types against, so it would see everything as `Any` and
never flag `attr-defined`. It must therefore be checked in the same run as
the source tree, as `uv run mypy --strict src/` already is.
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
