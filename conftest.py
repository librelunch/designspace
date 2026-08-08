"""Pytest configuration for the doctest gate.

Both jobs here serve
`pytest --doctest-modules --doctest-glob=*.md src docs README.md`: inject the
names every docstring example assumes, and keep collection away from the one
file under `docs/` that is configuration rather than prose.

**This file belongs at the repository root, not under `tests/`.** A conftest
applies only to items collected at or below its own directory, and nothing the
doctest gate walks is inside `tests/`. The fixture has to reach docstrings in
`src/designspace/**`, pages in `docs/**/*.md` and the README, which is the one
target at the root itself, and `collect_ignore` entries resolve relative to the
conftest's own directory, so `docs/conf.py` is unreachable from anywhere else.
"""

from __future__ import annotations

from typing import Any

import pytest

# `--doctest-modules` imports every module under the paths it is given, and
# this is Sphinx configuration rather than library code: nothing to test, and
# importing it is not free.
collect_ignore = [
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
