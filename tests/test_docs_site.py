"""Gates for the documentation site (PLAN.md, M13.5).

Three laws, in increasing cost:

1. the API reference lists every name in `__all__` — pure text, always runs;
2. every guide page carries at least one `>>>` block — the guard against the
   silent-zero hole, see below;
3. the site builds clean under `-W` with `nitpicky = True` — ~17s, so it runs
   only when `DESIGNSPACE_DOCS_BUILD` is set, and its CI job sets it.

Law 3 is opt-in by **environment variable, not by whether Sphinx imports**.
Keying it on the import would mean anyone who has ever run `uv run --extra docs`
silently pays ~17s on every later `pytest -q`, because that leaves Sphinx in the
project environment — a gate that turns itself on as a side effect of an
unrelated command is a gate people learn to work around. With an explicit
switch, the cost is asked for. When it is set but the `docs` extra is missing
the law **fails** rather than skipping: someone who asked for the build wants to
hear that it could not run.

Law 2 exists because a doctest gate that collects nothing reports green. M13
lost all 83 doctests under `src/designspace/build/` that way — pytest's default
`norecursedirs` contains `build` — and `pytest -q` stayed green throughout.
`docs/` is on `testpaths` for the same reason; this asserts the pages actually
carry the tests that setting is there to run.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

import designspace as ds

_DOCS = Path(__file__).resolve().parent.parent / "docs"
_GUIDES = sorted((_DOCS / "guides").glob("*.md"))
_BUILD_ENV_VAR = "DESIGNSPACE_DOCS_BUILD"


def test_reference_lists_every_export() -> None:
    """Every exported name appears in the API reference.

    Without this the reference silently stops covering the surface the moment
    a milestone exports something new — which is exactly what M13's export
    closure did (79 names to 91) and M13.5 did again (91 to 96).
    """
    text = (_DOCS / "reference.md").read_text()
    missing = [
        name for name in ds.__all__ if name != "__version__" and f"designspace.{name}\n" not in text
    ]
    assert not missing, (
        f"{len(missing)} exported names are absent from docs/reference.md: "
        f"{', '.join(sorted(missing))}"
    )


def test_guide_pages_exist() -> None:
    """The guide directory is not empty and is reachable from its index."""
    assert _GUIDES, "docs/guides/ has no pages"
    index = (_DOCS / "guides" / "index.md").read_text()
    orphans = [p.stem for p in _GUIDES if p.stem != "index" and p.stem not in index]
    assert not orphans, f"guide pages missing from the toctree: {', '.join(orphans)}"


@pytest.mark.parametrize("page", _GUIDES, ids=[p.stem for p in _GUIDES])
def test_guide_page_carries_doctests(page: Path) -> None:
    """Every guide page except the index carries a runnable example.

    `--doctest-glob=*.md` runs them; this asserts there is something to run,
    so a page cannot quietly become prose-only while the gate reports green.
    """
    if page.stem == "index":
        pytest.skip("the index is a table of contents, not a guide")
    assert ">>>" in page.read_text(), (
        f"{page.name} carries no `>>>` example. Guide pages are executable "
        f"documentation; see PLAN.md M13.5."
    )


def test_site_builds_clean(tmp_path: Path) -> None:
    """`sphinx-build -W` with `nitpicky = True` produces no warnings.

    Nitpicky rather than the default level because a default-level build was
    measured clean over the whole surface before any of this milestone's fixes
    landed — it could not have caught anything. Nitpicky caught a docstring
    napoleon renders with the wrong type, which the griffe gates in
    `test_docs.py` structurally cannot see: they never resolve a reference.

    Set `DESIGNSPACE_DOCS_BUILD=1` to run it (`uv sync --extra docs` first);
    CI's `docs` job does both.
    """
    if not os.environ.get(_BUILD_ENV_VAR):
        pytest.skip(f"set {_BUILD_ENV_VAR}=1 to build the site (~17s; needs the `docs` extra)")

    missing = [
        module
        for module in ("sphinx", "pydata_sphinx_theme", "myst_parser", "sphinx_copybutton")
        if importlib.util.find_spec(module) is None
    ]
    assert not missing, (
        f"{_BUILD_ENV_VAR} is set but the `docs` extra is not installed "
        f"(missing: {', '.join(missing)}). Run `uv sync --extra docs`."
    )

    result = subprocess.run(
        [sys.executable, "-m", "sphinx", "-b", "html", "-W", "-q", str(_DOCS), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "the docs site does not build clean:\n" + result.stderr + result.stdout
    )
