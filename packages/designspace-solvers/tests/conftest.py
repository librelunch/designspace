"""Shared setup for the backend tests.

The corpus lives in the core package's own test tree rather than here. These
tests run against it deliberately: a space written to exercise the library is a
far better test of a binding than one written to make the binding pass, and
reusing it means a change to the corpus reaches the bindings too.

The path is extended at import time rather than from a fixture, because the
test modules import corpus fixtures at their own module level, which runs
before any fixture does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE_TESTS = Path(__file__).resolve().parents[3] / "tests"

if str(_CORE_TESTS) not in sys.path:
    sys.path.insert(0, str(_CORE_TESTS))


@pytest.fixture(autouse=True)
def _quiet_optuna() -> None:
    """Keep Optuna's per-trial logging out of the test output."""
    optuna = pytest.importorskip("optuna")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
