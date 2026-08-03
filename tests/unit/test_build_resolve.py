"""M1 gate: builder + resolve pipeline for flat scalar spaces.

Per milestone gate: every implemented error-table row has a test asserting
the error class *and* that the message names the offending path; degenerate
scalars resolve; declaration order is preserved in Space.params.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError
from designspace.ir import BoolDomain, CategoricalDomain, IntegerDomain, OrdinalDomain, RealDomain


class TestDegenerateScalarsResolve:
    def test_real(self):
        space = ds.space(ds.param("lr").real(1e-5, 1.0))
        assert space.params["lr"].domain == RealDomain(1e-5, 1.0)

    def test_integer(self):
        space = ds.space(ds.param("n").integer(1, 8))
        assert space.params["n"].domain == IntegerDomain(1, 8)

    def test_categorical(self):
        space = ds.space(ds.param("algo").categorical("sgd", "adam"))
        assert space.params["algo"].domain == CategoricalDomain(("sgd", "adam"))

    def test_ordinal(self):
        space = ds.space(ds.param("size").ordinal("s", "m", "l"))
        assert space.params["size"].domain == OrdinalDomain(("s", "m", "l"))

    def test_bool(self):
        space = ds.space(ds.param("flag").bool())
        assert space.params["flag"].domain == BoolDomain()

    def test_constant_real_lo_eq_hi_is_legal(self):
        space = ds.space(ds.param("x").real(1.0, 1.0))
        assert space.params["x"].domain == RealDomain(1.0, 1.0)

    def test_single_value_categorical_is_legal(self):
        space = ds.space(ds.param("x").categorical("only"))
        assert space.params["x"].domain == CategoricalDomain(("only",))

    def test_single_value_ordinal_is_legal(self):
        space = ds.space(ds.param("x").ordinal("only"))
        assert space.params["x"].domain == OrdinalDomain(("only",))


class TestDeclarationOrder:
    def test_order_preserved(self):
        space = ds.space(
            ds.param("c").real(0.0, 1.0),
            ds.param("a").bool(),
            ds.param("b").integer(0, 5),
        )
        assert list(space.params.keys()) == ["c", "a", "b"]

    def test_n_params(self):
        space = ds.space(ds.param("a").bool(), ds.param("b").bool())
        assert space.n_params == 2


class TestRow1DuplicateNames:
    def test_duplicate_param_name_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0), ds.param("x").integer(0, 5))


class TestRow2TypeCount:
    def test_no_type_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x"))

    def test_multiple_types_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).integer(0, 5))


class TestRow3DuplicateValues:
    def test_categorical_duplicate_same_type_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical(1, 1))

    def test_categorical_type_tagged_distinct_is_legal(self):
        # 1 (int) and 1.0 (float) are distinct declared values.
        space = ds.space(ds.param("x").categorical(1, 1.0))
        assert space.params["x"].domain.values == (1, 1.0)

    def test_ordinal_duplicate_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").ordinal("a", "a"))


class TestRow4MixedTypeSharedImage:
    def test_shared_string_image_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical(1, "1"))


class TestRow5NameCharacters:
    @pytest.mark.parametrize("bad", ["a.b", "a[0]", "a]", "a["])
    def test_forbidden_characters_raise(self, bad):
        with pytest.raises(ResolutionError, match="path grammar"):
            ds.space(ds.param(bad).bool())


class TestRow6UndeclaredReference:
    def test_when_references_undeclared_param(self):
        # D-26 (superseding D-12): a `.when()` reference that resolves nowhere
        # locally is *tolerated* at construction — it may be an up-reference to
        # an enclosing scope that binds once this space is embedded. The row-6
        # error still fires (same class, same phase R, structure-only, no config
        # needed), only at the terminal-op finalization over the merged space.
        space = ds.space(ds.param("x").bool().when(ds.param("y")))
        with pytest.raises(ResolutionError, match="'y'"):
            space.sample_one(seed=0)
        with pytest.raises(ResolutionError, match="'y'"):
            space.validate({"x": True})


class TestRow7Cycles:
    def test_self_reference_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").bool().when(ds.param("x")))

    def test_two_param_cycle_raises(self):
        with pytest.raises(ResolutionError, match="cycle"):
            ds.space(
                ds.param("a").bool().when(ds.param("b")),
                ds.param("b").bool().when(ds.param("a")),
            )

    def test_diamond_dependency_is_not_a_false_cycle(self):
        # a and b both depend on root; c depends on both a and b. No cycle.
        space = ds.space(
            ds.param("root").bool(),
            ds.param("a").bool().when(ds.param("root")),
            ds.param("b").bool().when(ds.param("root")),
            ds.param("c").bool().when(ds.param("a").implies(ds.param("b"))),
        )
        assert space.n_params == 4


class TestRow8Bounds:
    def test_lo_gt_hi_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(2.0, 1.0))

    def test_integer_lo_gt_hi_raises(self):
        with pytest.raises(ResolutionError, match="'n'"):
            ds.space(ds.param("n").integer(5, 1))

    def test_non_finite_bound_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, float("inf")))

    def test_nan_bound_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(float("nan"), 1.0))


class TestRow10Quantized:
    def test_neither_step_nor_factor_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).quantized())

    def test_both_step_and_factor_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1, factor=2.0))

    def test_nonpositive_step_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.0))

    def test_factor_not_greater_than_one_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).quantized(factor=1.0))

    def test_valid_quantized_resolves(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1))
        assert space.params["x"].quantized is not None
        assert space.params["x"].quantized.step == 0.1


class TestRow11ModifierPlacement:
    def test_prior_dist_on_categorical_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical("a", "b").prior(object()))

    def test_prior_weights_on_real_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).prior(weights=[1.0, 2.0]))

    def test_quantized_on_categorical_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical("a", "b").quantized(step=1))


class TestRow14ArithmeticAndOrderingTypeErrors:
    def test_arithmetic_on_categorical_raises(self):
        with pytest.raises(ResolutionError, match="'flag'"):
            ds.space(
                ds.param("algo").categorical("sgd", "adam"),
                ds.param("flag").bool().when((ds.param("algo") + 1) == 2),  # type: ignore[operator]
            )

    def test_arithmetic_on_ordinal_raises(self):
        with pytest.raises(ResolutionError, match="'flag'"):
            ds.space(
                ds.param("size").ordinal("s", "m", "l"),
                ds.param("flag").bool().when((ds.param("size") + 1) == 2),  # type: ignore[operator]
            )

    def test_ordering_comparison_on_categorical_raises(self):
        with pytest.raises(ResolutionError, match="'flag'"):
            ds.space(
                ds.param("algo").categorical("sgd", "adam"),
                ds.param("flag").bool().when(ds.param("algo") > "sgd"),  # type: ignore[operator]
            )

    def test_ordinal_ordering_comparison_is_legal(self):
        space = ds.space(
            ds.param("size").ordinal("s", "m", "l"),
            ds.param("other").ordinal("s", "m", "l"),
            ds.param("flag").bool().when(ds.param("size") > ds.param("other")),
        )
        assert space.n_params == 3

    def test_categorical_equality_is_legal(self):
        space = ds.space(
            ds.param("algo").categorical("sgd", "adam"),
            ds.param("flag").bool().when(ds.param("algo") == "sgd"),
        )
        assert space.n_params == 2

    def test_categorical_is_in_is_legal(self):
        space = ds.space(
            ds.param("algo").categorical("sgd", "adam", "lbfgs"),
            ds.param("flag").bool().when(ds.param("algo").is_in("sgd", "adam")),
        )
        assert space.n_params == 2


class TestRow17Weights:
    def test_wrong_length_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical("a", "b").prior(weights=[1.0]))

    def test_negative_weight_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical("a", "b").prior(weights=[1.0, -1.0]))

    def test_all_zero_weights_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical("a", "b").prior(weights=[0.0, 0.0]))

    def test_bool_weights_wrong_length_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").bool().prior(weights=[1.0]))

    def test_valid_weights_resolve(self):
        space = ds.space(ds.param("x").categorical("a", "b").prior(weights=[1.0, 3.0]))
        assert space.params["x"].prior.values == (1.0, 3.0)


class TestRow21DefaultDomain:
    def test_real_default_out_of_bounds_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0).default(2.0))

    def test_integer_default_out_of_bounds_raises(self):
        with pytest.raises(ResolutionError, match="'n'"):
            ds.space(ds.param("n").integer(0, 5).default(10))

    def test_categorical_default_not_declared_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").categorical("a", "b").default("c"))

    def test_bool_default_wrong_type_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").bool().default(1))  # type: ignore[arg-type]

    def test_valid_default_resolves(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).default(0.5))
        assert space.params["x"].default == 0.5


class TestRow23TagsMeta:
    def test_empty_tag_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").bool().tag(""))

    def test_non_json_meta_value_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").bool().meta(fn=lambda: 1))

    def test_list_meta_value_is_accepted(self):
        # DECISIONS.md D-36 (corrected): row 23 gates "JSON-serializable"
        # (a list passes that bar) — recurses through the same codec as
        # `default`/`list_default` (see tests/conformance/test_identity.py
        # for the round-trip law).
        space = ds.space(ds.param("x").bool().meta(k=[1, 2]))
        assert dict(space.params["x"].meta) == {"k": [1, 2]}

    def test_dict_meta_value_is_accepted(self):
        space = ds.space(ds.param("x").bool().meta(k={"nested": 1}))
        assert dict(space.params["x"].meta) == {"k": {"nested": 1}}

    def test_tags_accumulate(self):
        space = ds.space(ds.param("x").bool().tag("a").tag("b"))
        assert space.params["x"].tags == frozenset({"a", "b"})

    def test_meta_merges_last_write_wins_per_key(self):
        space = ds.space(ds.param("x").bool().meta(a=1).meta(a=2, b=3))
        assert dict(space.params["x"].meta) == {"a": 2, "b": 3}


class TestExpressionBoundsOnRepeatedElementNotYetSupported:
    """M5 implements expression bounds on ordinary (non-lifted) scalar
    params — tests/unit/test_resolve_m5.py. A `.repeat()` element's own
    domain is a separate, still-unsupported case (DECISIONS.md D-29)."""

    def test_lift_element_expression_bound_raises(self):
        with pytest.raises(ResolutionError, match="repeated element"):
            ds.space(
                ds.param("y").real(0.0, 1.0),
                ds.param("xs").real(0.0, ds.param("y")).repeat(3),
            )


class TestNonParamExprInSpace:
    def test_rejects_non_paramexpr(self):
        with pytest.raises(ResolutionError):
            ds.space(42)  # type: ignore[arg-type]


class TestLastWriteWinsVsAccumulate:
    def test_prior_is_last_write_wins(self):
        space = ds.space(ds.param("x").real(1e-3, 1.0).prior(ds.Power(2.0)).log_scale())
        assert isinstance(space.params["x"].prior, ds.Log)

    def test_when_ands_multiple_calls(self):
        space = ds.space(
            ds.param("a").bool(),
            ds.param("b").bool(),
            ds.param("c").bool().when(ds.param("a")).when(ds.param("b")),
        )
        condition = space.params["c"].condition
        assert condition is not None
        assert condition.kind == "and"

    def test_quantized_last_write_wins(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1).quantized(step=0.2))
        assert space.params["x"].quantized.step == 0.2


class TestLogScaleIsPriorLogSugar:
    def test_log_scale_equivalent_to_prior_log(self):
        a = ds.space(ds.param("x").real(1e-5, 1.0).log_scale())
        b = ds.space(ds.param("x").real(1e-5, 1.0).prior(ds.Log()))
        assert a.params["x"].prior == b.params["x"].prior == ds.Log()
