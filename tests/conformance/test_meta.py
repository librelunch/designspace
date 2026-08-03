"""Conformance laws: `ds.param_from_def` (API.md, "Space — Metaprogramming";
PLAN.md M8 gate). `space_from_ir`/`map_params`/`without_constraints` join
this file once Stage 3 implements them.

"The IR is bidirectional": `param_from_def(pd)` must invert a resolved
`ParamDef` back into the exact `TypedParamExpr` view the fluent builder
would have produced, for every scalar/subset/permutation/list kind — proven
by re-resolving the reconstructed param alone and checking fingerprint
equality against the original single-param space. Struct/choice containers
cannot round-trip through a single `ParamDef` (their descendants live as
separate flat entries elsewhere in the space) — `param_from_def` raises
`TypeError` naming `space_from_ir` as the correct tool instead of silently
producing a descendant-less container (DECISIONS.md D-41).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import designspace as ds
from designspace.build._views import TypedParamExpr
from designspace.errors import ResolutionError
from designspace.ir import QuantizedSpec, RealDomain


def _single_param_space(view) -> ds.Space:
    return ds.space(view)


class TestParamFromDefScalarRoundTrip:
    @pytest.mark.parametrize(
        "view",
        [
            ds.param("x").real(0.0, 1.0),
            ds.param("x").real(0.0, 1.0, periodic=True),
            ds.param("x").integer(0, 10),
            ds.param("x").bool(),
            ds.param("x").categorical("a", "b", "c"),
            ds.param("x").ordinal("lo", "mid", "hi"),
            ds.param("x").subset(["a", "b", "c"], min_size=1, max_size=2),
            ds.param("x").permutation(["a", "b", "c"]),
        ],
    )
    def test_reconstructed_view_is_fingerprint_equal(self, view):
        original = _single_param_space(view)
        pd = original.params["x"]
        rebuilt_view = ds.param_from_def(pd)
        assert isinstance(rebuilt_view, TypedParamExpr)
        rebuilt = _single_param_space(rebuilt_view)
        assert rebuilt.fingerprint("full") == original.fingerprint("full")
        assert rebuilt.to_json() == original.to_json()

    def test_preserves_default_tags_meta(self):
        view = ds.param("x").real(0.0, 1.0).default(0.5).tag("t1", "t2").meta(a=1)
        original = _single_param_space(view)
        pd = original.params["x"]
        rebuilt = _single_param_space(ds.param_from_def(pd))
        assert rebuilt.fingerprint("full") == original.fingerprint("full")

    def test_preserves_prior_and_quantized(self):
        view = ds.param("x").real(1.0, 10.0).log_scale().quantized(step=0.5)
        original = _single_param_space(view)
        pd = original.params["x"]
        rebuilt = _single_param_space(ds.param_from_def(pd))
        assert rebuilt.fingerprint("full") == original.fingerprint("full")

    def test_preserves_condition(self):
        # Needs a 2-param space so the condition's reference resolves.
        original = ds.space(
            ds.param("g").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("g")),
        )
        pd = original.params["x"]
        rebuilt_view = ds.param_from_def(pd)
        rebuilt = ds.space(ds.param("g").bool(), rebuilt_view)
        assert rebuilt.fingerprint("full") == original.fingerprint("full")


class TestParamFromDefList:
    def test_single_level_repeat_round_trips(self):
        original = _single_param_space(ds.param("x").integer(0, 10).repeat(3))
        pd = original.params["x"]
        rebuilt_view = ds.param_from_def(pd)
        assert isinstance(rebuilt_view, TypedParamExpr)
        rebuilt = _single_param_space(rebuilt_view)
        assert rebuilt.fingerprint("full") == original.fingerprint("full")
        assert rebuilt.to_json() == original.to_json()

    def test_chained_repeat_round_trips(self):
        original = _single_param_space(ds.param("x").real(0.0, 1.0).repeat(2).repeat(3))
        pd = original.params["x"]
        rebuilt = _single_param_space(ds.param_from_def(pd))
        assert rebuilt.fingerprint("full") == original.fingerprint("full")
        assert rebuilt.to_json() == original.to_json()

    def test_repeat_with_list_default_round_trips(self):
        original = _single_param_space(ds.param("x").integer(0, 10).repeat(3).default([1, 2, 3]))
        pd = original.params["x"]
        rebuilt = _single_param_space(ds.param_from_def(pd))
        assert rebuilt.fingerprint("full") == original.fingerprint("full")


class TestParamFromDefStructChoiceRaise:
    def test_struct_container_raises_typeerror(self):
        original = ds.space(
            ds.param("s").space(ds.param("inner").integer(0, 5)),
        )
        pd = original.params["s"]
        with pytest.raises(TypeError, match="space_from_ir"):
            ds.param_from_def(pd)

    def test_choice_container_raises_typeerror(self):
        original = ds.space(ds.param("c").choice("a", "b"))
        pd = original.params["c"]
        with pytest.raises(TypeError, match="space_from_ir"):
            ds.param_from_def(pd)

    def test_repeated_struct_element_raises_typeerror(self):
        original = ds.space(
            ds.param("edges").space(ds.param("weight").real(0.0, 1.0)).repeat(2),
        )
        pd = original.params["edges"]
        with pytest.raises(TypeError, match="space_from_ir"):
            ds.param_from_def(pd)


# -- space_from_ir -----------------------------------------------------------


def _elaborate_space() -> ds.Space:
    return (
        ds.space(
            ds.param("solver").choice(
                "dpll",
                cdcl=ds.space(ds.param("restart").categorical("luby", "geometric")),
            ),
            ds.param("cfg").space(ds.param("depth").integer(1, 10)),
            ds.param("verbosity").ordinal("silent", "normal", "verbose"),
            ds.param("mask").subset(["a", "b", "c"], min_size=1),
            ds.param("order").permutation(["a", "b", "c"]),
            ds.param("weights").real(0.0, 1.0).repeat(3),
        )
        .forbid(ds.param("verbosity") >= "verbose")
        .encourage(ds.param("cfg.depth") < 5, tags=("perf",))
    )


class TestSpaceFromIrRoundTrip:
    def test_rebuilt_space_is_fingerprint_equal_to_hand_built(self):
        original = _elaborate_space()
        rebuilt = ds.space_from_ir(original.params, original.conditions, original.constraints)
        assert rebuilt.fingerprint("full") == original.fingerprint("full")
        assert rebuilt.fingerprint("sampling") == original.fingerprint("sampling")
        assert rebuilt.to_json() == original.to_json()

    def test_accepts_mapping_or_iterable_params(self):
        original = ds.space(ds.param("x").real(0.0, 1.0))
        via_mapping = ds.space_from_ir(original.params, original.conditions, original.constraints)
        via_list = ds.space_from_ir(
            list(original.params.values()), original.conditions, original.constraints
        )
        assert via_mapping.fingerprint("full") == via_list.fingerprint("full")
        assert via_mapping.fingerprint("full") == original.fingerprint("full")

    def test_preserves_anchors_and_meta(self):
        original = (
            ds.space(ds.param("x").real(0.0, 1.0)).anchor({"baseline": {"x": 0.5}}).meta(note="hi")
        )
        rebuilt = ds.space_from_ir(
            original.params,
            original.conditions,
            original.constraints,
            anchors=dict(original.anchors),
            meta=dict(original.meta_map),
        )
        assert rebuilt.fingerprint("full") == original.fingerprint("full")
        assert rebuilt.anchors == original.anchors

    def test_duplicate_path_raises(self):
        pd = ds.space(ds.param("x").real(0.0, 1.0)).params["x"]
        with pytest.raises(ResolutionError, match="duplicate"):
            ds.space_from_ir([pd, pd], (), ())

    def test_revalidates_bad_default(self):
        original = ds.space(ds.param("x").real(0.0, 1.0).default(0.5))
        bad_pd = replace(original.params["x"], default=5.0)  # outside [0, 1]
        with pytest.raises(ResolutionError):
            ds.space_from_ir([bad_pd], (), ())


class TestMapParams:
    def test_coarsening_example(self):
        # A representative "coarsening" rewrite: quantize every unquantized
        # real param onto a coarser grid, leaving other kinds untouched.
        original = ds.space(
            ds.param("x").real(0.0, 1.0),
            ds.param("y").real(0.0, 10.0),
            ds.param("k").integer(0, 5),
        )

        def coarsen(pd):
            if isinstance(pd.domain, RealDomain) and pd.quantized is None:
                return replace(pd, quantized=QuantizedSpec(step=0.1, factor=None, include_hi=False))
            return pd

        coarsened = original.map_params(coarsen)
        assert coarsened.params["x"].quantized is not None
        assert coarsened.params["y"].quantized is not None
        assert coarsened.params["k"].quantized is None
        assert coarsened.n_params == original.n_params
        assert coarsened.fingerprint("full") != original.fingerprint("full")
        for cfg in coarsened.sample_dicts(20, seed=0):
            assert coarsened.validate(cfg).valid

    def test_preserves_conditions_and_constraints(self):
        original = _elaborate_space()
        mapped = original.map_params(lambda pd: pd)  # identity rewrite
        assert mapped.fingerprint("full") == original.fingerprint("full")


class TestWithoutConstraints:
    def test_drops_only_tagged_constraints(self):
        space = (
            ds.space(ds.param("x").real(0.0, 1.0))
            .forbid(ds.param("x") > 0.9, tags=("safety",))
            .encourage(ds.param("x") < 0.5, tags=("perf",))
        )
        stripped = space.without_constraints(tags=("safety",))
        assert len(stripped.constraints) == 1
        assert stripped.constraints[0].tags == frozenset({"perf"})

    def test_empty_tags_is_a_no_op(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") > 0.9, tags=("safety",))
        assert space.without_constraints().fingerprint("full") == space.fingerprint("full")
