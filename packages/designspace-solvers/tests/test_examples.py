"""The example scripts, run end to end.

Each script is executed as written, `main` and all. They are the first thing a
reader of this package runs, and they exercise the bindings through their
documented entry points, so a change to the representation fails here rather
than in front of that reader.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_SCRIPTS = sorted(_EXAMPLES.glob("*.py"))


def test_the_examples_are_found() -> None:
    """The parametrized run below is silent when the glob matches nothing."""
    assert _SCRIPTS, f"no example scripts under {_EXAMPLES}"


@pytest.mark.parametrize("script", _SCRIPTS, ids=lambda path: path.stem)
def test_example_runs(script: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(str(script), run_name="__main__")
    assert capsys.readouterr().out, f"{script.name} printed nothing"
