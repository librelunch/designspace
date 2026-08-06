"""Conformance laws: margins (API.md, "Constraints and Feasibility" >
"Margins"; "Conformance Laws" > "Margins").

- Sign convention per comparison form.
- Boolean composition preserves the satisfaction invariant (`&` holds iff
  min(margin) >= 0, `|` holds iff max(margin) >= 0, `~p` negates), tested
  with hypothesis over random expression trees — no forbid/encourage
  wrapper, since margin is a structural property of the expression alone
  (DECISIONS.md D-4).
- `-0.0` never leaks out as a distinct sign from `0.0`.
- `.forbid()`/`.encourage()` polarity (D-4): a forbid's stored predicate
  names the *forbidden* state; a declared constraint's names the *desired*
  state.
- Continuous-`==` warning (row 25).
"""

from __future__ import annotations

import math
import warnings
from types import MappingProxyType

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

import designspace as ds
from designspace import Space
from designspace.eval import compute_activity, evaluate_bool, margin


def _margin_of(expr, config):
    space = _dummy_space(config)
    activity = compute_activity(space, config)
    return margin(expr, config, activity, space)


class _FakeParamDef:
    """Stand-in with just enough shape for `_ordinal_domain_of`'s `.domain`
    lookup (`None` is not an `OrdinalDomain`, so it's a safe non-match) and
    `compute_activity`'s M4 lift check (`type_kind` just needs to not be
    `"list"`)."""

    domain = None
    type_kind = "real"


def _dummy_space(config) -> Space:
    # No param here has a condition, and none is ordinal, so a Space with
    # the right param keys (and domain=None stand-ins) is enough for
    # compute_activity/margin/evaluate_bool.
    return Space(
        params=MappingProxyType({k: _FakeParamDef() for k in config}),  # type: ignore[misc]
        conditions=(),
    )


class TestMarginSignPerForm:
    def test_le_lt(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        config = {"a": 3.0, "b": 5.0}
        assert _margin_of(a <= b, config) == 2.0
        assert _margin_of(a < b, config) == 2.0

    def test_ge_gt(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        config = {"a": 5.0, "b": 3.0}
        assert _margin_of(a >= b, config) == 2.0
        assert _margin_of(a > b, config) == 2.0

    def test_eq(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        assert _margin_of(a == b, {"a": 3.0, "b": 3.0}) == 0.0
        assert _margin_of(a == b, {"a": 3.0, "b": 5.0}) == -2.0

    def test_ne(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        assert _margin_of(a != b, {"a": 3.0, "b": 3.0}) == 0.0
        assert _margin_of(a != b, {"a": 3.0, "b": 5.0}) == 2.0
        # "violated => 0; never negative"
        m = _margin_of(a != b, {"a": 3.0, "b": 3.0})
        assert m is not None and m >= 0

    def test_non_numeric_leaf_is_none(self):
        c = ds.param("c").categorical("x", "y")
        assert _margin_of(c == "x", {"c": "x"}) is None
        assert _margin_of(c == "x", {"c": "y"}) is None

    def test_boundary_is_never_negative_zero(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        for expr in (a <= b, a >= b, a == b):
            m = _margin_of(expr, {"a": 1.0, "b": 1.0})
            assert m is not None and m == 0.0
            assert math.copysign(1.0, m) == 1.0, f"got signed zero for {expr.kind}"
        m = _margin_of(~(a <= b), {"a": 1.0, "b": 1.0})
        assert m is not None and m == 0.0
        assert math.copysign(1.0, m) == 1.0


class TestBooleanComposition:
    def test_and_is_min(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        c, d = ds.param("c").real(-100, 100), ds.param("d").real(-100, 100)
        config = {"a": 1.0, "b": 5.0, "c": 10.0, "d": 2.0}
        m_left = _margin_of(a <= b, config)
        m_right = _margin_of(c <= d, config)
        m_and = _margin_of((a <= b) & (c <= d), config)
        assert m_left is not None and m_right is not None
        assert m_and == min(m_left, m_right)

    def test_or_is_max(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        c, d = ds.param("c").real(-100, 100), ds.param("d").real(-100, 100)
        config = {"a": 1.0, "b": 5.0, "c": 10.0, "d": 2.0}
        m_left = _margin_of(a <= b, config)
        m_right = _margin_of(c <= d, config)
        m_or = _margin_of((a <= b) | (c <= d), config)
        assert m_left is not None and m_right is not None
        assert m_or == max(m_left, m_right)

    def test_not_negates(self):
        a, b = ds.param("a").real(-100, 100), ds.param("b").real(-100, 100)
        config = {"a": 1.0, "b": 5.0}
        m = _margin_of(a <= b, config)
        assert m is not None
        assert _margin_of(~(a <= b), config) == -m

    def test_none_absorbs(self):
        a = ds.param("a").real(-100, 100)
        c = ds.param("c").categorical("x", "y")
        config = {"a": 1.0, "c": "x"}
        assert _margin_of((a <= 5) & (c == "x"), config) is None
        assert _margin_of((a <= 5) | (c == "x"), config) is None


@st.composite
def _leaf_and_margin(draw, suffix: str):
    a_val = draw(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False))
    b_val = draw(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False))
    op = draw(st.sampled_from(["le", "lt", "ge", "gt", "eq", "ne"]))
    if op in ("lt", "gt", "ne"):
        # Exact ties are a measure-zero boundary ambiguity, not a
        # composition-invariant violation: `<=`/`<` (and `>=`/`>`) share one
        # margin formula, so margin == 0 doesn't distinguish "holds" (<=)
        # from "doesn't" (<); `!=`'s margin is `abs(a-b)`, so margin == 0
        # means "doesn't hold" (equal), the same boundary shape as `lt`/`gt`.
        assume(a_val != b_val)
    a_name, b_name = f"a{suffix}", f"b{suffix}"
    a, b = ds.param(a_name).real(-1e7, 1e7), ds.param(b_name).real(-1e7, 1e7)
    expr = {
        "le": a <= b,
        "lt": a < b,
        "ge": a >= b,
        "gt": a > b,
        "eq": a == b,
        "ne": a != b,
    }[op]
    return expr, {a_name: a_val, b_name: b_val}


@given(st.data())
def test_composition_preserves_satisfaction_invariant(data):
    """`&` holds iff min(margin) >= 0; `|` holds iff max(margin) >= 0;
    `~p` holds iff margin(p) < 0 — random expression trees, per the
    conformance gate ("composition preserves satisfaction invariant")."""
    left_expr, left_cfg = data.draw(_leaf_and_margin(""))
    right_expr, right_cfg = data.draw(_leaf_and_margin("2"))
    config = {**left_cfg, **right_cfg}

    m_left = _margin_of(left_expr, config)
    m_right = _margin_of(right_expr, config)
    assert m_left is not None and m_right is not None

    and_expr = left_expr & right_expr
    or_expr = left_expr | right_expr
    not_expr = ~left_expr

    space = _dummy_space(config)
    activity = compute_activity(space, config)
    and_val = evaluate_bool(and_expr, config, activity, space)
    or_val = evaluate_bool(or_expr, config, activity, space)
    not_val = evaluate_bool(not_expr, config, activity, space)

    assert and_val == (min(m_left, m_right) >= 0)
    assert or_val == (max(m_left, m_right) >= 0)
    assert not_val == (m_left < 0)


class TestForbidEncouragePolarity:
    """D-4: a forbid's predicate names the forbidden (bad) state; a
    declared constraint's predicate names the desired (good) state."""

    def test_forbid_violated_when_predicate_true(self):
        space = ds.space(ds.param("lr").real(0.0, 1.0)).forbid(ds.param("lr") > 0.5)
        assert space.validate({"lr": 0.9}).valid is False
        assert space.validate({"lr": 0.1}).valid is True

    def test_encourage_never_affects_validity_but_flags_violation(self):
        space = ds.space(ds.param("x").real(0.0, 100.0)).encourage(ds.param("x") <= 10.0)
        result_ok = space.validate({"x": 5.0})
        result_bad = space.validate({"x": 50.0})
        assert result_ok.valid is True
        assert result_bad.valid is True  # encourage never affects feasibility
        assert result_ok.constraint_evals[0].satisfied is True
        assert result_bad.constraint_evals[0].satisfied is False

    def test_sampler_only_draws_safe_configs(self):
        space = ds.space(ds.param("lr").real(0.0, 1.0)).forbid(ds.param("lr") > 0.5)
        for _ in range(50):
            cfg = space.sample_one(seed=None)
            assert cfg["lr"] <= 0.5


class TestContinuousEqualityWarning:
    def test_warns_on_unquantized_real_equality(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.warns(UserWarning, match="measure-zero"):
            space.encourage(ds.param("x") == 0.5)

    def test_no_warning_for_quantized_real(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            space.encourage(ds.param("x") == 0.5)

    def test_no_warning_for_categorical(self):
        space = ds.space(ds.param("c").categorical("a", "b"))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            space.encourage(ds.param("c") == "a")

    def test_no_warning_when_real_compared_to_integer(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0),
            ds.param("n").integer(0, 10),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            space.encourage(ds.param("x") == ds.param("n"))
