"""Conformance law: **reference closure** — every param reference a space
stores names something declared in that space.

This is the generic detector for the bug class D-91 and its siblings came
from: a reference that lives somewhere the relocating code does not look,
and so keeps a pre-relocation path after merging. Every instance of it
fails the same way — the dangling path reads as Kleene-Unknown-from-
inactivity, which is the *permissive* direction, so a count silently
materializes `[]`, a hard per-element `.forbid()` silently stops deciding
feasibility, and `validate()` still reports `valid`.

Stating it as one invariant over every reference store, swept across every
corpus fixture and a generated grid of nesting routes, is what makes the
class caught rather than its instances. The four stores:

- `Space.conditions[].expr` and each `ParamDef.condition`
- `Space.constraints[].expr`
- `ListDomain.count` (D-21), at every lift level
- `ListDomain.element_constraints[].expr` (D-20), at every lift level

The predicate is the library's **own** `_is_declared` — the row-6 check —
rather than a reimplementation. The invariant is then exactly "every stored
reference would pass the reference check", and a second definition of
"declared" cannot drift from it. (It has to admit more than `space.params`
keys: an instance path `"stops[0].dwell"` resolves through its `"[]"`
template, and a lifted choice's discriminator template `"pipe[]"` resolves
through its owning lift, neither being a key of its own.)
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

import designspace as ds
from designspace.errors import ResolutionError
from designspace.ir import ListDomain
from designspace.resolve._expr_checks import _is_declared

_CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
if str(_CORPUS_DIR) not in sys.path:  # the corpus fixtures import by bare name
    sys.path.insert(0, str(_CORPUS_DIR))

CORPUS_FIXTURES = sorted(
    p.stem for p in _CORPUS_DIR.glob("*.py") if not p.stem.startswith(("test_", "_", "conftest"))
)


def reference_closure_violations(space: ds.Space) -> list[str]:
    """Every dangling reference in `space`, over all four stores."""
    declared: dict[str, Any] = dict(space.params)
    violations: list[str] = []

    def audit(paths: object, where: str) -> None:
        for path in sorted(paths):  # type: ignore[call-overload]
            if not _is_declared(path, declared):
                violations.append(f"{where} -> {path!r}")

    for condition in space.conditions:
        audit(condition.params, f"condition on {condition.target!r}")
    for constraint in space.constraints:
        audit(constraint.params, f"{constraint.kind}() constraint")
    for path, pd in space.params.items():
        if pd.condition is not None:
            audit(pd.condition.params, f"ParamDef {path!r} condition")
        domain: Any = pd.domain
        while isinstance(domain, ListDomain):
            if not isinstance(domain.count, int):
                audit(domain.count.params, f"{path!r} repeat() count")
            for constraint in domain.element_constraints:
                audit(constraint.params, f"{path!r} element {constraint.kind}() constraint")
            domain = domain.element_domain
    return violations


class TestCorpusReferenceClosure:
    """Swept over every corpus fixture, discovered from the directory so a
    newly added fixture inherits the invariant without being registered."""

    def test_the_sweep_is_not_empty(self) -> None:
        assert len(CORPUS_FIXTURES) >= 15

    @pytest.mark.parametrize("fixture", CORPUS_FIXTURES)
    def test_fixture_has_closed_references(self, fixture: str) -> None:
        space = importlib.import_module(fixture).build_space()
        assert reference_closure_violations(space) == []


# -- the generated nesting grid ------------------------------------------------
#
# Every reference-carrying declaration, placed at every route that relocates
# it. The bugs this exists for were all "works at root scope, silently broken
# one level in", so the axis that matters is the route, and the only way to
# be sure a fact is covered at every route is to build the product.

_ELEMENT_WITH_CONSTRAINT = ds.space(
    ds.param("lo").integer(0, 5),
    ds.param("hi").integer(0, 5),
).forbid(ds.param("lo") > ds.param("hi"))


def _fact_count_sibling() -> tuple[Any, ...]:
    return (
        ds.param("n").integer(2, 3),
        ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
    )


def _fact_count_arithmetic() -> tuple[Any, ...]:
    return (
        ds.param("n").integer(1, 2),
        ds.param("xs").real(0.0, 1.0).repeat(ds.param("n") + 1),
    )


def _fact_nested_count() -> tuple[Any, ...]:
    return (
        ds.param("m").integer(2, 3),
        ds.param("g").real(0.0, 1.0).repeat(ds.param("m")).repeat(2),
    )


def _fact_element_constraint() -> tuple[Any, ...]:
    return (ds.param("spans").space(_ELEMENT_WITH_CONSTRAINT).repeat(2),)


def _fact_condition_sibling() -> tuple[Any, ...]:
    return (
        ds.param("f").bool(),
        ds.param("y").real(0.0, 1.0).when(ds.param("f")),
    )


def _fact_bound_sibling() -> tuple[Any, ...]:
    return (
        ds.param("h").integer(2, 5),
        ds.param("k").integer(1, ds.param("h")),
    )


def _fact_inner_constraint() -> tuple[Any, ...]:
    return (
        ds.param("blk").space(
            ds.space(
                ds.param("p").integer(0, 5),
                ds.param("q").integer(0, 5),
            ).forbid(ds.param("p") > ds.param("q"))
        ),
    )


def _fact_lifted_choice() -> tuple[Any, ...]:
    return (ds.param("pipe").choice("a", b=ds.space(ds.param("w").real(0.0, 1.0))).repeat(2),)


FACTS = {
    "count_sibling": _fact_count_sibling,
    "count_arithmetic": _fact_count_arithmetic,
    "nested_count": _fact_nested_count,
    "element_constraint": _fact_element_constraint,
    "condition_sibling": _fact_condition_sibling,
    "bound_sibling": _fact_bound_sibling,
    "inner_constraint": _fact_inner_constraint,
    "lifted_choice": _fact_lifted_choice,
}


def _at_route(inner: tuple[Any, ...], route: str) -> ds.Space:
    if route == "root":
        return ds.space(*inner)
    if route == "struct":
        return ds.space(ds.param("g").space(*inner))
    if route == "variant":
        return ds.space(ds.param("m").choice("off", on=ds.space(*inner)))
    if route == "struct_in_struct":
        return ds.space(ds.param("a").space(ds.param("b").space(*inner)))
    if route == "variant_in_struct":
        return ds.space(ds.param("a").space(ds.param("m").choice("off", on=ds.space(*inner))))
    if route == "struct_in_variant":
        return ds.space(ds.param("m").choice("off", on=ds.space(ds.param("g").space(*inner))))
    if route == "lifted_struct":
        return ds.space(ds.param("row").space(ds.space(*inner)).repeat(2))
    raise AssertionError(f"unknown route {route!r}")


ROUTES = [
    "root",
    "struct",
    "variant",
    "struct_in_struct",
    "variant_in_struct",
    "struct_in_variant",
    "lifted_struct",
]


# A cell whose *shape* is unsupported rather than whose behaviour is wrong.
# Placing a struct- or choice-elemented lift inside another lift's element
# composes to D-24's boundary ("a struct/choice element nested under more
# than one .repeat() level"), so the cell must raise — and asserting that it
# raises is as much a law as the passing cells, since the alternative
# discovered here was silently invalid configs.
EXPECTED_D24 = {
    ("element_constraint", "lifted_struct"),
    ("lifted_choice", "lifted_struct"),
}


class TestNestingGrid:
    """Each cell asserts the three things that together caught every bug in
    this class: references close, finalization accepts the space, and it
    round-trips through sample/validate."""

    @pytest.mark.parametrize("route", ROUTES)
    @pytest.mark.parametrize("fact", sorted(FACTS))
    def test_cell(self, fact: str, route: str) -> None:
        if (fact, route) in EXPECTED_D24:
            with pytest.raises(ResolutionError, match="D-24"):
                _at_route(FACTS[fact](), route)
            return
        space = _at_route(FACTS[fact](), route)
        assert reference_closure_violations(space) == []
        space.fingerprint()  # forces the deferred finalization pass
        for seed in range(3):
            config = space.sample_one(seed=seed)
            result = space.validate(config)
            assert result.valid, (fact, route, config, result.param_errors)

    def test_the_grid_is_the_full_product(self) -> None:
        assert len(FACTS) * len(ROUTES) == 56

    def test_every_expected_error_cell_is_in_the_grid(self) -> None:
        """Guards the guard: a renamed fact or route must not silently turn
        an expected-error cell into an untested one."""
        for fact, route in EXPECTED_D24:
            assert fact in FACTS and route in ROUTES


class TestGridCatchesTheClass:
    """The grid earns its keep only if a cell actually fails when a
    reference dangles. Rather than trust that, break one on purpose and
    assert the detector fires — the same shape every bug in this class had.
    """

    def test_a_dangling_count_is_detected(self) -> None:
        from dataclasses import replace

        space = _at_route(_fact_count_sibling(), "struct")
        assert reference_closure_violations(space) == []

        listed = space.params["g.xs"].domain
        assert isinstance(listed, ListDomain)
        # Re-introduce exactly D-91's bug: the pre-relocation bare path.
        broken_domain = replace(listed, count=ds.param("n"))
        broken = replace(
            space,
            params={**space.params, "g.xs": replace(space.params["g.xs"], domain=broken_domain)},
        )
        violations = reference_closure_violations(broken)
        assert violations == ["'g.xs' repeat() count -> 'n'"]

    def test_a_dangling_element_constraint_is_detected(self) -> None:
        from dataclasses import replace

        space = _at_route(_fact_element_constraint(), "struct")
        assert reference_closure_violations(space) == []

        listed = space.params["g.spans"].domain
        assert isinstance(listed, ListDomain)
        template = listed.element_constraints[0]
        # D-20's bug: the template keeps its pre-relocation params.
        broken_template = replace(template, params=frozenset({"spans[].lo", "spans[].hi"}))
        broken_domain = replace(listed, element_constraints=(broken_template,))
        broken = replace(
            space,
            params={
                **space.params,
                "g.spans": replace(space.params["g.spans"], domain=broken_domain),
            },
        )
        assert reference_closure_violations(broken) == [
            "'g.spans' element forbid() constraint -> 'spans[].hi'",
            "'g.spans' element forbid() constraint -> 'spans[].lo'",
        ]
