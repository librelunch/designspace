"""Unit tests for the representation layer's value-level pieces.

Covered: the `ChartApply` expression node's own shape and evaluation
semantics, the `Encoding` protocol's `hasattr` predicates, and
`Representation`'s value-level algebra, meaning `__post_init__`'s
`invertible` derivation, `then` and `check`.

`ChartApply` is not user-constructible, API.md having `represent/_transport.py`
emit it, so it is built directly here against the internal AST and
evaluation modules, as `test_expr.py` builds expression nodes directly.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace import ParamExpr
from designspace.charts._builtin import LogChart, UniformChart
from designspace.eval import compute_activity, evaluate_arith
from designspace.expr import ChartApply, Field, Sum
from designspace.ir import RealDomain
from designspace.represent import (
    Encoding,
    Representation,
    can_encode,
    has_decode_expr,
    has_prop_expr,
    has_rewrite,
    is_measure_preserving,
)
from designspace.resolve._expr_checks import _vector_base


def _chart_apply(path: str, chart, lo: float, hi: float) -> ChartApply:
    return ChartApply(ParamExpr(path=path), chart, "real", RealDomain(lo, hi))


class TestChartApplyNodeShape:
    def test_kind_children_params(self):
        node = _chart_apply("u", UniformChart(0.0, 1.0), 0.0, 1.0)
        assert node.kind == "chart_apply"
        assert node.children == (node.operand,)
        assert node.params == frozenset({"u"})

    def test_field_wrapped_operand_params(self):
        base = ParamExpr(path="pipeline")
        node = ChartApply(Field(base, "rate"), UniformChart(0.0, 1.0), "real", RealDomain(0.0, 1.0))
        assert node.params == frozenset({"pipeline"})

    def test_defaults(self):
        node = _chart_apply("u", UniformChart(0.0, 1.0), 0.0, 1.0)
        assert node.prior is None
        assert node.quantized is None
        assert node.periodic is False

    def test_not_exported_from_top_level_package(self):
        assert not hasattr(ds, "ChartApply")


class TestVectorBaseUnwrapsChartApply:
    """`_vector_base` unwraps a `ChartApply`.

    Without that, a transported aggregate over an encoded param, whether
    `Sum(ChartApply(...))` or `Sum(ChartApply(Field(...)))`, fails
    `_referenced_domain`'s bare-reference check on its own decode.
    """

    def test_unwraps_bare_reference(self):
        ref = ParamExpr(path="dropout")
        node = ChartApply(ref, UniformChart(0.0, 1.0), "real", RealDomain(0.0, 1.0))
        assert _vector_base(node) is ref

    def test_unwraps_field_then_chart_apply(self):
        ref = ParamExpr(path="pipeline")
        field = Field(ref, "rate")
        node = ChartApply(field, UniformChart(0.0, 1.0), "real", RealDomain(0.0, 1.0))
        assert _vector_base(node) is ref

    def test_plain_field_still_unwraps_without_chart_apply(self):
        ref = ParamExpr(path="pipeline")
        assert _vector_base(Field(ref, "rate")) is ref


class TestChartApplyEvaluation:
    def test_scalar_position(self):
        space = ds.space(ds.param("u").real(0.0, 1.0))
        node = _chart_apply("u", UniformChart(0.0, 10.0), 0.0, 10.0)
        config = {"u": 0.25}
        activity = compute_activity(space, config)
        assert evaluate_arith(node, config, activity, space) == pytest.approx(2.5)

    def test_vector_position_maps_element_wise(self):
        space = ds.space(ds.param("w").real(0.0, 1.0).repeat(3))
        chart = LogChart(1.0, 100.0)
        node = Sum(_chart_apply("w", chart, 1.0, 100.0))
        config = {"w": 3, "w[0]": 0.0, "w[1]": 0.5, "w[2]": 1.0}
        activity = compute_activity(space, config)
        # LogChart(1, 100).from_unit(u) == 100 ** u -- 1 + 10 + 100.
        assert evaluate_arith(node, config, activity, space) == pytest.approx(111.0)

    def test_vector_position_propagates_inactive_unknown(self):
        space = ds.space(
            ds.param("gate").bool(),
            ds.param("w").real(0.0, 1.0).repeat(3).when(ds.param("gate")),
        )
        node = Sum(_chart_apply("w", UniformChart(0.0, 1.0), 0.0, 1.0))
        config = {"gate": False}
        activity = compute_activity(space, config)
        from designspace.eval import Unknown

        assert isinstance(evaluate_arith(node, config, activity, space), Unknown)

    def test_field_wrapped_vector_position(self):
        pipeline = ds.param("pipeline").space(ds.param("rate").real(0.0, 1.0)).repeat(2)
        space = ds.space(pipeline)
        base = ParamExpr(path="pipeline")
        chart_apply = ChartApply(
            Field(base, "rate"), UniformChart(0.0, 10.0), "real", RealDomain(0.0, 10.0)
        )
        node = Sum(chart_apply)
        config = {"pipeline": 2, "pipeline[0].rate": 0.0, "pipeline[1].rate": 1.0}
        activity = compute_activity(space, config)
        assert evaluate_arith(node, config, activity, space) == pytest.approx(10.0)


# -- Encoding protocol predicates --------------------------------------------


class _Bare:
    def target(self, param):  # pragma: no cover -- structural stub
        raise NotImplementedError

    def decode(self, param, value):  # pragma: no cover -- structural stub
        raise NotImplementedError


class _WithEncode(_Bare):
    def encode(self, param, value):  # pragma: no cover -- structural stub
        raise NotImplementedError


class _WithDecodeExpr(_Bare):
    def decode_expr(self, param):  # pragma: no cover -- structural stub
        raise NotImplementedError


class _WithPropExpr(_Bare):
    def prop_expr(self, param, name):  # pragma: no cover -- structural stub
        raise NotImplementedError


class _WithRewrite(_Bare):
    def rewrite(self, param, node):  # pragma: no cover -- structural stub
        raise NotImplementedError


class _MeasurePreserving(_Bare):
    def measure_preserving(self) -> bool:
        return True


class _NotMeasurePreserving(_Bare):
    def measure_preserving(self) -> bool:
        return False


class TestEncodingPredicates:
    def test_bare_has_no_optional_capability(self):
        bare = _Bare()
        assert not can_encode(bare)
        assert not has_decode_expr(bare)
        assert not has_prop_expr(bare)
        assert not has_rewrite(bare)
        assert is_measure_preserving(bare) is False  # absent reads as False

    def test_each_capability_detected_independently(self):
        assert can_encode(_WithEncode())
        assert has_decode_expr(_WithDecodeExpr())
        assert has_prop_expr(_WithPropExpr())
        assert has_rewrite(_WithRewrite())

    def test_measure_preserving_reads_the_declared_value(self):
        assert is_measure_preserving(_MeasurePreserving()) is True
        assert is_measure_preserving(_NotMeasurePreserving()) is False

    def test_bare_satisfies_encoding_protocol_structurally(self):
        stub: Encoding = _Bare()
        assert hasattr(stub, "target") and hasattr(stub, "decode")


# -- Representation: invertible derivation, then, check ----------------------


def _phenotype_space(hi: float = 4.0) -> ds.Space:
    return ds.space(ds.param("x").real(0.0, hi))


def _genotype_space(hi: float = 1.0) -> ds.Space:
    return ds.space(ds.param("x").real(0.0, hi))


def _scale_decode(factor: float):
    return lambda g: {"x": g["x"] * factor}


def _scale_encode(factor: float):
    return lambda p: {"x": p["x"] / factor}


class TestRepresentationInvertibleDerivation:
    def test_no_encode_is_not_invertible_and_raises_a_named_message(self):
        rep = Representation(
            source=_phenotype_space(),
            target=_genotype_space(),
            decode=_scale_decode(4.0),
        )
        assert rep.invertible is False
        with pytest.raises(TypeError, match="not invertible"):
            rep.encode({"x": 1.0})

    def test_explicit_encode_none_matches_the_spec_illustrative_call(self):
        # `Representation(source=..., target=..., decode=..., encode=None)`
        # (API.md, "The Representation Layer" -- "Supplied") must type-check
        # and behave exactly like omitting `encode` entirely.
        rep = Representation(
            source=_phenotype_space(), target=_genotype_space(), decode=lambda g: g, encode=None
        )
        assert rep.invertible is False

    def test_supplied_encode_is_invertible(self):
        rep = Representation(
            source=_phenotype_space(),
            target=_genotype_space(),
            decode=_scale_decode(4.0),
            encode=_scale_encode(4.0),
        )
        assert rep.invertible is True
        assert rep.encode({"x": 2.0}) == {"x": 0.5}
        assert rep.decode({"x": 0.5}) == {"x": 2.0}


class TestRepresentationThen:
    def test_composes_decode_and_encode(self):
        space_a = _phenotype_space(hi=4.0)
        space_b = _genotype_space(hi=2.0)  # rep1.target == rep2.source (fingerprint)
        space_c = _genotype_space(hi=1.0)
        rep1 = Representation(
            source=space_a,
            target=space_b,
            decode=_scale_decode(2.0),
            encode=_scale_encode(2.0),
            encoded=("x",),
            measure_preserving=True,
        )
        rep2 = Representation(
            source=space_b,
            target=space_c,
            decode=_scale_decode(2.0),
            encode=_scale_encode(2.0),
            encoded=("y",),
            measure_preserving=True,
        )
        composed = rep1.then(rep2)
        assert composed.source is space_a
        assert composed.target is space_c
        assert composed.decode({"x": 0.5}) == {"x": 2.0}  # 0.5 * 2 * 2
        assert composed.encode({"x": 2.0}) == {"x": 0.5}  # 2.0 / 2 / 2
        assert composed.invertible is True
        assert composed.measure_preserving is True
        assert composed.encoded == ("x", "y")

    def test_measure_preserving_is_a_conjunction(self):
        space_a = _phenotype_space(4.0)
        space_b = _genotype_space(2.0)
        space_c = _genotype_space(1.0)
        rep1 = Representation(
            source=space_a, target=space_b, decode=_scale_decode(2.0), measure_preserving=True
        )
        rep2 = Representation(
            source=space_b, target=space_c, decode=_scale_decode(2.0), measure_preserving=False
        )
        assert rep1.then(rep2).measure_preserving is False

    def test_not_invertible_when_either_side_is_not(self):
        space_a = _phenotype_space(4.0)
        space_b = _genotype_space(2.0)
        space_c = _genotype_space(1.0)
        rep1 = Representation(source=space_a, target=space_b, decode=_scale_decode(2.0))
        rep2 = Representation(
            source=space_b,
            target=space_c,
            decode=_scale_decode(2.0),
            encode=_scale_encode(2.0),
        )
        assert rep1.then(rep2).invertible is False

    def test_mismatched_fingerprint_raises_typeerror(self):
        space_a = _phenotype_space(4.0)
        space_b = _genotype_space(2.0)
        unrelated = ds.space(ds.param("y").real(0.0, 1.0))
        rep1 = Representation(source=space_a, target=space_b, decode=_scale_decode(2.0))
        rep_unrelated_source = Representation(source=unrelated, target=space_a, decode=lambda g: g)
        with pytest.raises(TypeError, match="fingerprint-equal"):
            rep1.then(rep_unrelated_source)


class TestRepresentationCheck:
    def test_sound_representation_reports_ok(self):
        rep = Representation(
            source=_phenotype_space(hi=2.0),
            target=_genotype_space(hi=1.0),
            decode=_scale_decode(2.0),
            encode=_scale_encode(2.0),
        )
        result = rep.check(n=50, seed=0)
        assert result.n == 50
        assert result.ok is True
        assert result.failures == ()

    def test_decode_totality_violation_is_reported(self):
        # `x * 100` on a genotype in [0, 1] lands far outside the source's
        # `[0, 2]` domain for almost every draw -- a genuine decode-totality
        # violation `check()` exists to catch.
        rep = Representation(
            source=_phenotype_space(hi=2.0),
            target=_genotype_space(hi=1.0),
            decode=_scale_decode(100.0),
        )
        result = rep.check(n=20, seed=0)
        assert result.ok is False
        assert any(f.law == "decode_totality" and f.count > 0 for f in result.failures)

    def test_check_never_raises_on_a_violation(self):
        rep = Representation(
            source=_phenotype_space(hi=2.0),
            target=_genotype_space(hi=1.0),
            decode=lambda g: {"x": -1.0},  # always out of domain
        )
        result = rep.check(n=10, seed=0)
        assert result.ok is False
        assert result.n == 10
