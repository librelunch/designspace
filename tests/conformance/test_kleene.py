"""Conformance laws: Kleene three-valued logic (API.md, "Expressions" >
"Three-valued semantics"; "Conformance Laws" > "Kleene").

- The truth table, exhaustive over all 9 (a, b) combinations for `&`/`|`,
  and all 3 for `~`.
- `ds.count` range rule: Unknown iff the comparison outcome differs across
  `[t, t + u]`.
- Rule 1: any predicate over an inactive param is Unknown; `is_active()` is
  total.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

import designspace as ds
from designspace.build._space import Space
from designspace.eval import Unknown, compute_activity, evaluate_bool

T, F, U = True, False, "U"


class _FakeParamDef:
    """Stand-in with just enough shape for `_ordinal_domain_of`'s `.domain`
    lookup (`None` is not an `OrdinalDomain`, so it's a safe non-match)."""

    domain = None


def _dummy_space(config) -> Space:
    # evaluate_bool only consults `space.params[...].domain` for ordinal
    # ordering comparisons; none of these tests use ordinals, so a Space
    # with the right param keys (and domain=None stand-ins) is enough.
    return Space(
        params=MappingProxyType({k: _FakeParamDef() for k in config}),  # type: ignore[misc]
        conditions=(),
    )


def _config_activity(**states: bool | str) -> tuple[dict, dict, Space]:
    config: dict = {}
    activity: dict = {}
    for name, state in states.items():
        if state == U:
            activity[name] = False
        else:
            activity[name] = True
            config[name] = state
    return config, activity, _dummy_space(config)


def _assert_kleene(result, expected) -> None:
    if expected == U:
        assert isinstance(result, Unknown), f"expected Unknown, got {result!r}"
    else:
        assert result is expected, f"expected {expected!r}, got {result!r}"


AND_TABLE = {
    (T, T): T,
    (T, U): U,
    (T, F): F,
    (U, T): U,
    (U, U): U,
    (U, F): F,
    (F, T): F,
    (F, U): F,
    (F, F): F,
}

OR_TABLE = {
    (T, T): T,
    (T, U): T,
    (T, F): T,
    (U, T): T,
    (U, U): U,
    (U, F): U,
    (F, T): T,
    (F, U): U,
    (F, F): F,
}

NOT_TABLE = {T: F, U: U, F: T}


class TestKleeneTruthTable:
    @pytest.mark.parametrize("a_state,b_state", list(AND_TABLE.keys()))
    def test_and(self, a_state, b_state):
        config, activity, space = _config_activity(a=a_state, b=b_state)
        expr = ds.param("a") & ds.param("b")
        _assert_kleene(evaluate_bool(expr, config, activity, space), AND_TABLE[(a_state, b_state)])

    @pytest.mark.parametrize("a_state,b_state", list(OR_TABLE.keys()))
    def test_or(self, a_state, b_state):
        config, activity, space = _config_activity(a=a_state, b=b_state)
        expr = ds.param("a") | ds.param("b")
        _assert_kleene(evaluate_bool(expr, config, activity, space), OR_TABLE[(a_state, b_state)])

    @pytest.mark.parametrize("a_state", list(NOT_TABLE.keys()))
    def test_not(self, a_state):
        config, activity, space = _config_activity(a=a_state)
        expr = ~ds.param("a")
        _assert_kleene(evaluate_bool(expr, config, activity, space), NOT_TABLE[a_state])


class TestRule1InactiveIsUnknown:
    def test_predicate_over_inactive_param_is_unknown(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        config = {"flag": False}
        activity = compute_activity(space, config)
        result = evaluate_bool(ds.param("x") > 0.5, config, activity, space)
        assert isinstance(result, Unknown)

    def test_is_active_is_total(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        for flag_value in (True, False):
            config = {"flag": flag_value}
            activity = compute_activity(space, config)
            result = evaluate_bool(ds.param("x").is_active(), config, activity, space)
            assert result is flag_value  # never Unknown

    def test_if_inactive_coalesces_to_fallback(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        config = {"flag": False}
        activity = compute_activity(space, config)
        expr = ds.param("x").if_inactive(0.0) < 5.0
        assert evaluate_bool(expr, config, activity, space) is True

    def test_if_inactive_passes_through_when_active(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        config = {"flag": True, "x": 0.9}
        activity = compute_activity(space, config)
        expr = ds.param("x").if_inactive(0.0) < 0.5
        assert evaluate_bool(expr, config, activity, space) is False


class TestOrdinalOrderingByDeclarationPosition:
    """Ordinals compare by declaration position, not by the raw value —
    this is the one place a bare Python `>`/`<` on the stored value would
    give a silently wrong answer."""

    def test_param_vs_literal(self):
        space = ds.space(ds.param("size").ordinal("s", "m", "l"))
        config = {"size": "l"}
        activity = compute_activity(space, config)
        # "l" < "s" alphabetically, but l is declared *after* s.
        assert evaluate_bool(ds.param("size") > "s", config, activity, space) is True
        assert evaluate_bool(ds.param("size") < "s", config, activity, space) is False
        assert evaluate_bool(ds.param("size") >= "l", config, activity, space) is True

    def test_param_vs_param(self):
        space = ds.space(
            ds.param("a").ordinal("s", "m", "l"),
            ds.param("b").ordinal("s", "m", "l"),
        )
        config = {"a": "m", "b": "s"}
        activity = compute_activity(space, config)
        assert evaluate_bool(ds.param("a") > ds.param("b"), config, activity, space) is True

    def test_numeric_valued_ordinal_still_uses_declaration_order(self):
        # Declared in decreasing numeric order: raw-value comparison would
        # give the opposite answer from declaration-position comparison.
        space = ds.space(ds.param("level").ordinal(30, 20, 10))
        config = {"level": 10}
        activity = compute_activity(space, config)
        # 10 is declared *last* (highest position), so it's the greatest.
        assert evaluate_bool(ds.param("level") > 30, config, activity, space) is True


def _count_config_activity(*states: bool | str) -> tuple[dict, dict, Space]:
    return _config_activity(**{f"b{i}": s for i, s in enumerate(states)})


def _bool_exprs(n: int):
    return tuple(ds.param(f"b{i}") for i in range(n))


class TestCountRange:
    """`ds.count` tracks `[t, t+u]`; Unknown iff the comparison outcome
    differs across the range."""

    def test_all_known_ge_definite_true(self):
        config, activity, space = _count_config_activity(T, T, F)
        expr = ds.count(*_bool_exprs(3)) >= 2
        assert evaluate_bool(expr, config, activity, space) is True

    def test_all_known_ge_definite_false(self):
        config, activity, space = _count_config_activity(T, F, F)
        expr = ds.count(*_bool_exprs(3)) >= 2
        assert evaluate_bool(expr, config, activity, space) is False

    def test_unknown_but_outcome_constant_across_range(self):
        # t=2 (b0,b1 True), u=1 (b2 unknown) -> range [2,3]; ">= 2" holds
        # for both endpoints -> definite True despite the Unknown operand.
        config, activity, space = _count_config_activity(T, T, U)
        expr = ds.count(*_bool_exprs(3)) >= 2
        assert evaluate_bool(expr, config, activity, space) is True

    def test_unknown_and_outcome_varies_across_range(self):
        # t=1, u=1 -> range [1,2]; ">= 2" is False at 1, True at 2 -> Unknown.
        config, activity, space = _count_config_activity(T, U, F)
        expr = ds.count(*_bool_exprs(3)) >= 2
        assert isinstance(evaluate_bool(expr, config, activity, space), Unknown)

    def test_eq_unknown_when_threshold_achievable(self):
        # t=1, u=2 -> range [1,3]; count could be exactly 2 -> Unknown.
        config, activity, space = _count_config_activity(T, U, U)
        expr = ds.count(*_bool_exprs(3)) == 2
        assert isinstance(evaluate_bool(expr, config, activity, space), Unknown)

    def test_eq_definite_false_when_threshold_unreachable(self):
        # t=0, u=1 -> range [0,1]; count can never be 2 -> definite False.
        config, activity, space = _count_config_activity(F, U)
        expr = ds.count(*_bool_exprs(2)) == 2
        assert evaluate_bool(expr, config, activity, space) is False

    def test_ne_definite_true_when_threshold_unreachable(self):
        config, activity, space = _count_config_activity(F, U)
        expr = ds.count(*_bool_exprs(2)) != 5
        assert evaluate_bool(expr, config, activity, space) is True

    def test_ne_unknown_when_threshold_achievable(self):
        config, activity, space = _count_config_activity(T, U, U)
        expr = ds.count(*_bool_exprs(3)) != 2
        assert isinstance(evaluate_bool(expr, config, activity, space), Unknown)

    def test_lt_gt_le_endpoints(self):
        # t=1, u=1 -> range [1,2].
        config, activity, space = _count_config_activity(T, U)
        c = ds.count(*_bool_exprs(2))
        assert evaluate_bool(c < 1, config, activity, space) is False  # neither endpoint < 1
        # true at count=1, false at count=2 -> Unknown
        assert isinstance(evaluate_bool(c <= 1, config, activity, space), Unknown)
        assert evaluate_bool(c > 0, config, activity, space) is True  # both endpoints > 0
        assert evaluate_bool(c >= 3, config, activity, space) is False  # neither endpoint >= 3

    def test_count_on_right_hand_side(self):
        config, activity, space = _count_config_activity(T, T, F)
        expr = 2 <= ds.count(*_bool_exprs(3))  # noqa: SIM300 - deliberately reversed operand order
        assert evaluate_bool(expr, config, activity, space) is True
