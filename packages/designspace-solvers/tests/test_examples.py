"""The example scripts, run end to end.

Each script is executed as written, `main` and all. They are the first thing a
reader of this package runs, and they exercise the bindings through their
documented entry points, so a change to the representation fails here rather
than in front of that reader.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_SCRIPTS = sorted(_EXAMPLES.glob("*.py"))
# A script that starts a real race needs R and the R package irace, so its
# parameter carries the marker and a run without R deselects it. Naming the
# script outright rather than searching its source for the call keeps a script
# that merely translates a space from being marked by accident. Adding a script
# that races without listing it here fails every run that has no R, which is
# the signal to add it.
_IRACE_SCRIPTS = {"irace_racing"}


def test_the_examples_are_found() -> None:
    """The parametrized run below is silent when the glob matches nothing."""
    assert _SCRIPTS, f"no example scripts under {_EXAMPLES}"

    stems = {p.stem for p in _SCRIPTS}
    stale = sorted(_IRACE_SCRIPTS - stems)
    assert not stale, f"_IRACE_SCRIPTS names scripts that no longer exist: {', '.join(stale)}"


def _script_param(script: Path) -> Any:
    marks = [pytest.mark.requires_irace] if script.stem in _IRACE_SCRIPTS else []
    return pytest.param(script, id=script.stem, marks=marks)


@pytest.mark.parametrize("script", [_script_param(s) for s in _SCRIPTS])
def test_example_runs(script: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(str(script), run_name="__main__")
    assert capsys.readouterr().out, f"{script.name} printed nothing"
