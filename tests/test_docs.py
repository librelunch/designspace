"""Documentation gates for the public surface.

Six laws, each scoped to exactly what `designspace.__all__` exports. The
scoping is why they run on griffe rather than on ruff or `__doc__`:

- **Ruff cannot express it.** Ruff's `D1xx` missing-docstring rules never
  fire in this repo, because every implementation module is private, as
  `builder/_space.py` and `ir/_domain.py` are, and ruff treats a member of a
  private module as non-public. Ruff is also file-local, so it could never
  learn that `Space` is public by way of `designspace/__init__.py`'s
  `__all__`. Measured: `ruff check --select D1 src/` reported zero findings
  against a surface that was 124 docstrings short.
- **A runtime `__doc__` scan cannot either.** `@dataclass` synthesizes a
  `__doc__` from the signature, so `ds.Space.__doc__` is a truthy
  `"Space(params: ...)"` string even with no class docstring. Griffe reads
  the source statically and reports the absence.

What each member owes, by category:

| category | owes |
|---|---|
| exported name (class, function, type alias) | its own docstring |
| public method | its own docstring; its parameters documented |
| public property | its own docstring |
| public instance attribute | an entry in the owner's `Attributes` section |
| `ClassVar` discriminator | nothing |

The last row is the view types' `type_kind`. API.md, "Builder view types"
says the views "add no state beyond `ParamExpr`, have no serialized
footprint, and do not appear in the IR", so the attribute is build-layer
plumbing rather than surface a user reads or sets.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import griffe
import pytest

import designspace as ds

_SRC = Path(__file__).resolve().parent.parent / "src"

# A document that ships with the repository and not with the package.
_REPO_ONLY_DOC = re.compile(r"\b(?:API|PLAN|PROGRESS|DECISIONS|CLAUDE)\.md\b")
# An error-table row, cited singly or as a run.
_ROW_CITATION = re.compile(r"\brows?\s+\d+(?:\s*(?:,|and|or|to)\s*\d+)*")
# A private implementation module, as `represent/_build.py`.
_PRIVATE_MODULE = re.compile(r"\b[a-z_]+/_[a-z_]+\.py\b")
_NOT_SELF_CONTAINED = [
    ("a repository-only document", _REPO_ONLY_DOC),
    ("an error-table row", _ROW_CITATION),
    ("a private module", _PRIVATE_MODULE),
]

PACKAGE = griffe.load(
    "designspace",
    search_paths=[str(_SRC)],
    docstring_parser="numpy",
    resolve_aliases=True,
)


def _exports() -> Iterator[tuple[str, Any]]:
    """Yield `(name, griffe object)` for every export except `__version__`.

    Iterating `ds.__all__` rather than griffe's own `is_public` is
    deliberate: griffe additionally counts each subpackage, `builder` and
    `ir` among them, as a public member of the package, and those are
    internal structure rather than surface.
    """
    for name in sorted(ds.__all__):
        if name == "__version__":
            continue
        yield name, PACKAGE[name]


def _public_members(obj: Any) -> Iterator[tuple[str, Any]]:
    for name, member in obj.members.items():
        if not name.startswith("_"):
            yield name, member


def _is_property(member: Any) -> bool:
    return "property" in member.labels


def _is_method(member: Any) -> bool:
    return member.kind is griffe.Kind.FUNCTION


def _is_instance_attribute(member: Any) -> bool:
    return "instance-attribute" in member.labels and not _is_property(member)


def _documented(obj: Any) -> bool:
    return obj.docstring is not None and bool(obj.docstring.value.strip())


def _is_protocol(obj: Any) -> bool:
    return any(str(base) == "Protocol" for base in obj.bases)


def _build_targets() -> tuple[list[tuple[str, Any]], list[tuple[str, Any]], dict[str, list[str]]]:
    """Partition the public surface into the three things the laws check."""
    documentable: list[tuple[str, Any]] = []
    callables: list[tuple[str, Any]] = []
    attributes: dict[str, list[str]] = {}

    for name, obj in _exports():
        documentable.append((name, obj))
        if obj.kind is griffe.Kind.FUNCTION:
            callables.append((name, obj))
        if not obj.is_class:
            continue
        # A Protocol's members have no body to demonstrate. The worked
        # example belongs on the protocol class, showing an implementation
        # of the whole thing, which is what an author needs. Its members
        # still owe a docstring; they are exempt from the example law alone,
        # and the class itself is not exempt.
        protocol = _is_protocol(obj)
        for member_name, member in _public_members(obj):
            label = f"{name}.{member_name}"
            if _is_method(member):
                documentable.append((label, member))
                if not protocol:
                    callables.append((label, member))
            elif _is_property(member):
                documentable.append((label, member))
            elif _is_instance_attribute(member):
                attributes.setdefault(name, []).append(member_name)

    return documentable, callables, attributes


PROTOCOLS = [(name, obj) for name, obj in _exports() if obj.is_class and _is_protocol(obj)]


DOCUMENTABLE, CALLABLES, ATTRIBUTES = _build_targets()

DOCUMENTABLE_IDS = [label for label, _ in DOCUMENTABLE]
CALLABLE_IDS = [label for label, _ in CALLABLES]
ATTRIBUTE_OWNERS = sorted(ATTRIBUTES)


@contextmanager
def _griffe_warnings() -> Generator[list[str], None, None]:
    """Capture WARNING-level records from griffe's own logger.

    Griffe reports docstring problems through `logging`, not by returning
    them, so this is the only way to see them. DEBUG-level loader chatter
    shares the logger and is filtered out by level.
    """
    captured: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                captured.append(record.getMessage())

    logger = logging.getLogger("griffe")
    handler = _Collector()
    logger.addHandler(handler)
    try:
        yield captured
    finally:
        logger.removeHandler(handler)


def _sections(obj: Any, kind: griffe.DocstringSectionKind) -> list[Any]:
    if not _documented(obj):
        return []
    return [s for s in obj.docstring.parse("numpy") if s.kind is kind]


def _documented_names(obj: Any, kind: griffe.DocstringSectionKind) -> set[str]:
    names: set[str] = set()
    for section in _sections(obj, kind):
        for entry in section.value:
            names.add(entry.name.lstrip("*"))
    return names


def _expected_parameters(obj: Any) -> list[str]:
    """Signature parameters a NumPy `Parameters` section owes an entry for."""
    expected = []
    for parameter in obj.parameters:
        if parameter.name in ("self", "cls"):
            continue
        expected.append(parameter.name.lstrip("*"))
    return expected


@pytest.mark.parametrize(("label", "obj"), DOCUMENTABLE, ids=DOCUMENTABLE_IDS)
def test_public_surface_is_documented(label: str, obj: Any) -> None:
    """Every exported name, public method, and public property has a docstring."""
    assert _documented(obj), (
        f"{label} is exported (or is a public member of an exported class) but has "
        f"no docstring. The public surface is user documentation."
    )


@pytest.mark.parametrize("owner", ATTRIBUTE_OWNERS, ids=ATTRIBUTE_OWNERS)
def test_public_attributes_are_documented(owner: str) -> None:
    """Every public instance attribute appears in its class's `Attributes` section.

    NumPy style documents dataclass fields on the class rather than one
    docstring per field, so this is the coverage check for every field of
    the IR data model.
    """
    obj = PACKAGE[owner]
    documented = _documented_names(obj, griffe.DocstringSectionKind.attributes)
    missing = [name for name in ATTRIBUTES[owner] if name not in documented]
    assert not missing, (
        f"{owner} has public attributes absent from its `Attributes` section: {', '.join(missing)}"
    )


@pytest.mark.parametrize(("label", "obj"), DOCUMENTABLE, ids=DOCUMENTABLE_IDS)
def test_docstrings_parse_as_numpy(label: str, obj: Any) -> None:
    """No docstring produces a griffe parse warning.

    This catches a `Parameters` entry naming something the signature does
    not have, which is how a NumPy block silently rots after a rename, and
    malformed section syntax.
    """
    if not _documented(obj):
        pytest.skip("covered by test_public_surface_is_documented")
    with _griffe_warnings() as warnings:
        obj.docstring.parse("numpy")
    assert not warnings, f"{label} docstring: " + "; ".join(warnings)


@pytest.mark.parametrize(("label", "obj"), CALLABLES, ids=CALLABLE_IDS)
def test_signature_parameters_are_documented(label: str, obj: Any) -> None:
    """Every signature parameter appears in the `Parameters` section.

    Griffe warns about the converse (a documented parameter missing from
    the signature) but not about this direction, so the check is written
    out here.
    """
    if not _documented(obj):
        pytest.skip("covered by test_public_surface_is_documented")
    expected = _expected_parameters(obj)
    if not expected:
        return
    documented = _documented_names(obj, griffe.DocstringSectionKind.parameters)
    missing = [name for name in expected if name not in documented]
    assert not missing, (
        f"{label} takes {', '.join(missing)} but its `Parameters` section does not document them."
    )


def test_every_export_has_an_example() -> None:
    """Every callable a user invokes carries a runnable `>>>` example.

    Scoped to callables. An example on an IR dataclass would only echo a
    repr, and `repr(Space)` is a multi-line `mappingproxy` blob that is both
    unreadable and brittle as expected output. `--doctest-modules` executes
    the examples; this law asserts only that they exist.
    """
    missing = [
        label for label, obj in CALLABLES if _documented(obj) and ">>>" not in obj.docstring.value
    ]
    assert not missing, (
        f"{len(missing)} public callables have no `>>>` example: {', '.join(sorted(missing))}"
    )


@pytest.mark.parametrize(
    ("label", "obj"),
    PROTOCOLS,
    ids=[label for label, _ in PROTOCOLS],
)
def test_every_protocol_has_an_implementation_example(label: str, obj: Any) -> None:
    """Every protocol shows a worked implementation on the class itself.

    A Protocol's members are exempt from the example law, a `...` body
    having nothing to demonstrate, so the obligation moves here, where an
    author
    can see a whole implementation at once. Without this the exemption
    would silently lose the examples that matter most.
    """
    assert _documented(obj) and ">>>" in obj.docstring.value, (
        f"{label} is a protocol a consumer implements; its docstring must show "
        f"a worked implementation."
    )


@pytest.mark.parametrize(("label", "obj"), DOCUMENTABLE, ids=DOCUMENTABLE_IDS)
def test_published_docstrings_are_self_contained(label: str, obj: Any) -> None:
    """No published docstring points at something its reader cannot open.

    These docstrings are the API reference, so their reader has the package
    and not the repository. `API.md`, the error table and the private
    modules are all on the far side of that line: naming one gives the
    reader a reference that resolves for the maintainer who wrote it and for
    nobody else. The docstring states the thing instead, or names the public
    route to it.

    The same rule holds for authored site prose, enforced over `docs/` in
    `tests/test_docs_site.py`.
    """
    if not _documented(obj):
        return
    text = obj.docstring.value
    offenders = [
        f"{kind}: {match.group(0)!r}"
        for kind, p in _NOT_SELF_CONTAINED
        for match in p.finditer(text)
    ]
    assert not offenders, (
        f"{label}'s docstring is published as the API reference but names "
        f"something its reader has no copy of:\n  " + "\n  ".join(offenders)
    )
