"""Conformance law: immutability and copy-on-write (API.md, "Errors,
Concurrency": "All public objects — expressions, spaces, IR dataclasses,
charts — are immutable after construction and safe to share across threads.
RNG state is passed explicitly; nothing mutates shared state.").

The thread-safety claim ships no locking, so there is nothing concurrent to
test. Its entire content is structural, in two halves:

1. **Frozen** — no public object accepts attribute assignment, and the
   mappings they expose are read-only views rather than live dicts.
2. **Copy-on-write** — every chainable operation returns a *new* object and
   leaves its receiver byte-identical. This is the half a caller actually
   relies on when sharing one `Space` across threads: `space.forbid(...)`
   handing back a new space is only safe if `space` itself is untouched.

Half 1 was asserted for expression nodes only (`tests/unit/test_expr.py`)
and half 2 not systematically at all, so a newly added un-frozen IR
dataclass, or an operation that mutated in place, would have passed. Both
halves are swept over the exported surface here rather than spot-checked,
so a new export inherits them.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType
from typing import Any

import pytest

import designspace as ds

EXPORTED_DATACLASSES = sorted(
    name
    for name in ds.__all__
    if dataclasses.is_dataclass(getattr(ds, name, None)) and isinstance(getattr(ds, name), type)
)


def _space() -> ds.Space:
    return ds.space(
        ds.param("lr").real(1e-5, 1.0).log_scale(),
        ds.param("n").integer(1, 8),
        ds.param("mode").categorical("a", "b"),
        ds.param("xs").real(0.0, 1.0).repeat(3),
    ).forbid(ds.param("lr") > 0.5)


class TestEveryExportedDataclassIsFrozen:
    def test_the_sweep_is_not_empty(self) -> None:
        assert len(EXPORTED_DATACLASSES) >= 20

    @pytest.mark.parametrize("name", EXPORTED_DATACLASSES)
    def test_declared_frozen(self, name: str) -> None:
        cls = getattr(ds, name)
        assert cls.__dataclass_params__.frozen, f"{name} is a mutable dataclass"


class TestSpaceIsFrozenAndExposesReadOnlyViews:
    def test_attribute_assignment_raises(self) -> None:
        space = _space()
        with pytest.raises(dataclasses.FrozenInstanceError):
            space.params = {}  # type: ignore[misc]

    def test_params_mapping_is_read_only(self) -> None:
        space = _space()
        assert isinstance(space.params, MappingProxyType)
        with pytest.raises(TypeError):
            space.params["injected"] = None  # type: ignore[index]

    def test_paramdef_assignment_raises(self) -> None:
        space = _space()
        with pytest.raises(dataclasses.FrozenInstanceError):
            space.params["lr"].path = "nope"  # type: ignore[misc]

    def test_meta_and_anchors_are_read_only(self) -> None:
        space = (
            _space()
            .meta(objective="loss")
            .anchor({"base": {"lr": 0.1, "n": 2, "mode": "a", "xs": [0.0, 0.5, 1.0]}})
        )
        with pytest.raises(TypeError):
            space.anchors["injected"] = {}  # type: ignore[index]


class TestCopyOnWrite:
    """Every chainable operation returns a new object and leaves the
    receiver byte-identical — asserted through `fingerprint()`, which is
    exactly "identical valid-config sets, measure, and document"."""

    @staticmethod
    def _unchanged(before: ds.Space, operation: Any) -> bool:
        fingerprint = before.fingerprint()
        params = dict(before.params)
        result = operation(before)
        assert result is not before
        return before.fingerprint() == fingerprint and dict(before.params) == params

    @pytest.mark.parametrize(
        ("label", "operation"),
        [
            ("forbid", lambda s: s.forbid(ds.param("n") > 4)),
            ("require", lambda s: s.require(ds.param("n") <= 4)),
            ("encourage", lambda s: s.encourage(ds.param("n") <= 4)),
            ("discourage", lambda s: s.discourage(ds.param("n") > 4)),
            ("meta", lambda s: s.meta(note="x")),
            (
                "anchor",
                lambda s: s.anchor({"a": {"lr": 0.1, "n": 2, "mode": "a", "xs": [0.0] * 3}}),
            ),
            ("extend", lambda s: s.extend(ds.param("extra").bool())),
            ("freeze", lambda s: s.freeze(n=3)),
            ("slice", lambda s: s.slice(n=3)),
            ("select", lambda s: s.select("lr")),
            ("map_params", lambda s: s.map_params(lambda pd: pd)),
            ("without_constraints", lambda s: s.without_constraints(tags=())),
        ],
    )
    def test_operation_leaves_receiver_unchanged(self, label: str, operation: Any) -> None:
        assert self._unchanged(_space(), operation)

    @pytest.mark.parametrize(
        ("label", "operation"),
        [
            ("sample_one", lambda s: s.sample_one(seed=0)),
            ("sample_dicts", lambda s: s.sample_dicts(20, seed=0)),
            ("sampling_report", lambda s: s.sampling_report(n=20, seed=0)),
            ("validate", lambda s: s.validate(s.sample_one(seed=0))),
            ("apply_defaults", lambda s: s.apply_defaults({})),
            ("represent", lambda s: s.represent()),
            ("to_json", lambda s: s.to_json()),
        ],
    )
    def test_read_only_surface_never_mutates(self, label: str, operation: Any) -> None:
        space = _space()
        fingerprint = space.fingerprint()
        operation(space)
        assert space.fingerprint() == fingerprint

    def test_builder_modifiers_are_copy_on_write(self) -> None:
        """The same law one level down: a `ParamExpr` modifier returns a new
        expression rather than rebinding the receiver's own state."""
        base = ds.param("x").real(0.0, 1.0)
        tagged = base.tag("a")
        assert tagged is not base
        assert base.tags == frozenset()
        assert tagged.tags == frozenset({"a"})
        assert ds.space(base).fingerprint() != ds.space(tagged).fingerprint()

    def test_repeated_use_of_one_expr_is_independent(self) -> None:
        """Reusing a single built param in two spaces must not let one
        space's resolution leak into the other."""
        shared = ds.param("x").real(0.0, 1.0)
        first = ds.space(shared).forbid(ds.param("x") > 0.9)
        second = ds.space(shared)
        assert len(first.constraints) == 1
        assert len(second.constraints) == 0

    def test_a_representation_does_not_mutate_its_source(self) -> None:
        space = _space()
        fingerprint = space.fingerprint()
        rep = space.represent()
        rep.check(n=20, seed=0)
        rep.decode(rep.target.sample_one(seed=0))
        assert space.fingerprint() == fingerprint
        assert rep.source.fingerprint() == fingerprint


class TestRngIsPassedExplicitly:
    def test_same_seed_same_draw(self) -> None:
        space = _space()
        assert space.sample_one(seed=7) == space.sample_one(seed=7)

    def test_sampling_does_not_advance_shared_state(self) -> None:
        """ "RNG state is passed explicitly ... nothing mutates shared
        state": two independent spaces drawing at the same seed cannot
        influence one another's stream."""
        a, b = _space(), _space()
        first = a.sample_one(seed=11)
        b.sample_dicts(50, seed=11)
        assert a.sample_one(seed=11) == first
