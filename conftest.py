"""Pytest configuration shared by the whole suite.

Two jobs, both consequences of M13 putting `--doctest-modules` in `addopts`:
inject the names every docstring example assumes, and keep collection away
from the one module in the tree that is not importable by design.
"""

from __future__ import annotations

from typing import Any

import pytest

# `--doctest-modules` imports every module under `testpaths`, and this one
# raises `ResolutionError` at import on purpose: it is a `mypy --strict`
# fixture for the M4.6 view types (fed to mypy by tests/typing/
# test_static_typing.py, never executed). Without this entry the whole
# collection aborts.
collect_ignore = [
    "tests/typing/_row2_and_wrong_type_modifier.py",
    # M13.5 put `docs/` on `testpaths` so the guide pages' `>>>` blocks run.
    # That also puts `docs/conf.py` in `--doctest-modules`' path, where it is
    # Sphinx configuration rather than library code and has nothing to test.
    "docs/conf.py",
]


@pytest.fixture(autouse=True)
def _doctest_names(doctest_namespace: dict[str, Any]) -> None:
    """Make `ds` and `np` available to every docstring example.

    Following the numpy/pandas convention: examples read as the user would
    write them after `import designspace as ds`, without repeating that
    import in all ~116 of them. The rendered docs carry the preamble
    instead.

    Injection is invisible to a static analyser, so every module carrying
    examples also declares `import designspace as ds` under
    `if TYPE_CHECKING:` — never executed, but it is what makes an IDE
    resolve `ds` in a doctest and flag a genuine typo there instead of
    graying the whole block out. This fixture remains the only thing that
    binds the name at run time.
    """
    import numpy as np

    import designspace as ds

    doctest_namespace["ds"] = ds
    doctest_namespace["np"] = np
