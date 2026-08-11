"""Conformance laws: `ds.param_from_def` and `ds.space_from_ir`.

See API.md, "Space: Metaprogramming".

"The IR is bidirectional": `param_from_def(pd)` must invert a resolved
`ParamDef` into the `TypedParamExpr` view the fluent builder would have
produced, for every scalar, subset, permutation and list kind. That is
proven by re-resolving the reconstructed param alone and checking
fingerprint equality against the original single-param space.

A struct or choice container cannot round-trip through a single `ParamDef`,
its descendants living as separate flat entries elsewhere in the space, so
`param_from_def` raises `TypeError` naming `space_from_ir` as the right tool
rather than producing a descendant-less container.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import designspace as ds
from designspace import TypedParamExpr
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


class TestKindMatchesDomain:
    """A hand-assembled `ParamDef` states its kind twice, and the two must
    agree. `type_kind` and `domain` are in bijection, and only a record built
    outside the builders can separate them: a `ParamExpr` carries its kind on
    the view class, so no fluent declaration can. Both routes that accept IR
    check it, and so does an `Encoding.target` returning one.
    """

    def test_space_from_ir_rejects_mismatched_kind(self):
        pd = ds.space(ds.param("x").real(0.0, 1.0)).params["x"]
        with pytest.raises(ResolutionError, match=r"'x'.*'bool'.*RealDomain.*'real'"):
            ds.space_from_ir([replace(pd, type_kind="bool")], (), ())

    def test_param_from_def_rejects_mismatched_kind(self):
        pd = ds.space(ds.param("x").integer(1, 8)).params["x"]
        with pytest.raises(ResolutionError, match=r"'x'.*'categorical'.*IntegerDomain"):
            ds.param_from_def(replace(pd, type_kind="categorical"))

    def test_unknown_kind_is_a_resolution_error(self):
        """A misspelled kind names no domain class, so it fails the same
        check rather than escaping as a lookup error from the view table."""
        pd = ds.space(ds.param("x").integer(1, 8)).params["x"]
        with pytest.raises(ResolutionError, match=r"'x'.*'rael'"):
            ds.space_from_ir([replace(pd, type_kind="rael")], (), ())

    def test_domain_that_is_not_a_domain_is_rejected(self):
        pd = ds.space(ds.param("x").real(0.0, 1.0)).params["x"]
        with pytest.raises(ResolutionError, match=r"'x'.*not a domain type"):
            ds.space_from_ir([replace(pd, domain="real")], (), ())

    def test_list_element_mismatch_is_rejected(self):
        """A lift restates the pairing on its `ListDomain`, so the element is
        checked at its own path."""
        pd = ds.space(ds.param("xs").real(0.0, 1.0).repeat(3)).params["xs"]
        bad = replace(pd, domain=replace(pd.domain, element_kind="bool"))
        with pytest.raises(ResolutionError, match=r"'xs\[\]'.*'bool'.*RealDomain"):
            ds.space_from_ir([bad], (), ())

    def test_encoding_target_mismatch_is_rejected(self):
        """The likeliest way to write one: retag a parameter and forget to
        replace the domain alongside it."""

        class _RetagOnly:
            def target(self, param):
                return replace(param, type_kind="real", chart=None)

            def decode(self, param, value):
                return round(value)

            def encode(self, param, value):
                return float(value)

        s = ds.space(ds.param("depth").integer(1, 8))
        with pytest.raises(ResolutionError, match=r"'depth'.*'real'.*IntegerDomain"):
            s.represent(lambda pd: _RetagOnly() if pd.type_kind == "integer" else None)

    def test_a_faithful_retag_still_resolves(self):
        """The check bites only on disagreement: rewriting both fields
        together is what an encoding is supposed to do."""

        class _ToReal:
            def target(self, param):
                return replace(
                    param,
                    type_kind="real",
                    domain=RealDomain(float(param.domain.lo), float(param.domain.hi)),
                    default=None,
                    chart=None,
                )

            def decode(self, param, value):
                return round(value)

            def encode(self, param, value):
                return float(value)

        s = ds.space(ds.param("depth").integer(1, 8))
        rep = s.represent(lambda pd: _ToReal() if pd.type_kind == "integer" else None)
        assert rep.target.params["depth"].type_kind == "real"


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
