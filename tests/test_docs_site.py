"""Gates for the documentation site (PLAN.md, M13.5 and M13.6).

Six laws, in increasing cost. The first five are pure text or AST and always
run; only the sixth builds anything.

1. the API reference lists every name in `__all__`;
2. every guide page carries at least one `>>>` block — the guard against the
   silent-zero hole, see below;
3. every `examples/*.py` has a page under `docs/examples/` and appears in its
   toctree (M13.6);
4. every `{literalinclude}` on those pages resolves: the file exists and each
   `:pyobject:` names a top-level def in it (M13.6). Example pages carry no
   `>>>` of their own by design — their code is pulled from the scripts
   `tests/test_examples.py` runs, so requiring doctests there would force back
   exactly the duplication `literalinclude` removes. This law is what replaces
   law 2 for them: rename a step function and `pytest -q` fails at once,
   rather than the page quietly rendering an empty code block;
5. no U+2014 in documentation prose (M13.6). Two commits established this by
   hand and nothing protected it. Source-level, not rendered: the rendered
   count was the right measure for auditing inherited docstrings, but the
   enforceable law is over what the author writes;
6. the site builds clean under `-W` with `nitpicky = True` — ~17s, so it runs
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

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import designspace as ds

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"
_EXAMPLES = _ROOT / "examples"
_GUIDES = sorted((_DOCS / "guides").glob("*.md"))
_EXAMPLE_PAGES = sorted((_DOCS / "examples").glob("*.md"))
_EXAMPLE_SCRIPTS = sorted(_EXAMPLES.glob("*.py"))
# `_build` is gitignored output, not authored prose, and `conf.py` excludes it
# from the build for the same reason.
_DOC_SOURCES = sorted(p for p in _DOCS.rglob("*.md") if "_build" not in p.parts)
_BUILD_ENV_VAR = "DESIGNSPACE_DOCS_BUILD"

_EM_DASH = "—"

# ```{literalinclude} <path>\n:pyobject: <name>\n``` — the only form the example
# pages use. Anchored at the fence so a path mentioned in prose cannot match.
_LITERALINCLUDE = re.compile(
    r"^```\{literalinclude\}\s*(?P<path>\S+)\s*$\n(?P<options>(?:^:.*$\n)*)",
    re.MULTILINE,
)
_PYOBJECT = re.compile(r"^:pyobject:\s*(?P<name>\S+)\s*$", re.MULTILINE)


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


def test_every_example_has_a_page() -> None:
    """Every script under `examples/` is documented and reachable.

    Glob-driven for the same reason `tests/test_examples.py` is: a new example
    is covered the moment it lands, rather than when someone remembers to
    extend a list.
    """
    assert _EXAMPLE_SCRIPTS, "examples/ has no scripts"
    index = (_DOCS / "examples" / "index.md").read_text()

    # `examples/01_simulated_annealing.py` -> the page whose name starts `01-`.
    numbered = {p.name.split("-", 1)[0] for p in _EXAMPLE_PAGES if p.stem != "index"}
    undocumented = [s.name for s in _EXAMPLE_SCRIPTS if s.name.split("_", 1)[0] not in numbered]
    assert not undocumented, (
        f"examples with no page under docs/examples/: {', '.join(undocumented)}"
    )

    orphans = [p.stem for p in _EXAMPLE_PAGES if p.stem != "index" and p.stem not in index]
    assert not orphans, f"example pages missing from the toctree: {', '.join(orphans)}"


@pytest.mark.parametrize("page", _EXAMPLE_PAGES, ids=[p.stem for p in _EXAMPLE_PAGES])
def test_example_page_literalincludes_resolve(page: Path) -> None:
    """Every `{literalinclude}` on an example page points at real code.

    This is what makes a narrative page safe to write. The code lives only in
    `examples/`, so the page can never disagree with what runs; the risk it
    trades for is a silently empty code block after a rename. Sphinx would
    catch that too, but only under `DESIGNSPACE_DOCS_BUILD`, which is not set
    on an ordinary `pytest -q`.
    """
    text = page.read_text()
    matches = list(_LITERALINCLUDE.finditer(text))
    if page.stem == "index":
        assert not matches, "the examples index is navigation, not a walkthrough"
        return

    assert matches, f"{page.name} pulls in no code; example pages are walkthroughs of a script"

    for match in matches:
        target = (page.parent / match.group("path")).resolve()
        assert target.is_file(), f"{page.name}: literalinclude target does not exist: {target}"

        names = _PYOBJECT.findall(match.group("options"))
        assert names, (
            f"{page.name}: literalinclude of {target.name} has no `:pyobject:`. "
            f"Pulling a whole script into a narrative page is not the intent."
        )
        top_level = {
            node.name
            for node in ast.parse(target.read_text()).body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }
        missing = [name for name in names if name not in top_level]
        assert not missing, (
            f"{page.name}: {target.name} defines no top-level {', '.join(missing)}. "
            f"A renamed step function empties the code block silently."
        )


@pytest.mark.parametrize(
    "path",
    [*_DOC_SOURCES, *_EXAMPLE_SCRIPTS, _EXAMPLES / "README.md"],
    ids=lambda p: str(p.relative_to(_ROOT)),
)
def test_no_em_dash_in_documentation_prose(path: Path) -> None:
    """Documentation prose carries no U+2014.

    Objective, so it is gated. Register is not: second-person counts and
    antithesis counts are editorial judgment, and a threshold test over them
    would be brittle and would invite gaming.
    """
    lines = [
        f"  line {i}: {line.strip()}"
        for i, line in enumerate(path.read_text().splitlines(), start=1)
        if _EM_DASH in line
    ]
    assert not lines, f"{path.relative_to(_ROOT)} contains U+2014:\n" + "\n".join(lines)


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
        for module in (
            "sphinx",
            "pydata_sphinx_theme",
            "myst_parser",
            "sphinx_copybutton",
            "sphinx_design",
        )
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
