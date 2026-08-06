"""Conformance laws: Kleene three-valued logic (API.md, "Expressions" >
"Three-valued semantics"; "Conformance Laws" > "Kleene").

- The truth table, exhaustive over all 9 (a, b) combinations for `&`/`|`,
  and all 3 for `~`.
- `ds.count` range rule: Unknown iff the comparison outcome differs across
  `[t, t + u]`.
- Rule 1: any predicate over an inactive param is Unknown; `is_active()` is
  total.
- Rule 3: `.when()` coerces Unknown to False, cascading deactivation.
- Rule 4: the constraint verbs coerce Unknown to inapplicable
  (`margin=None`).
- Rule 5 (M10.5/D-71): `.if_inactive()` discriminates Unknown's provenance —
  coalesces inactivity alone, propagates a *pending* (partial-eval, unset)
  operand and a *permanent* (rule-6 emptiness) one untouched.
- Rule 7: bound-origin couplings follow rule 4 (inapplicable, not an error).
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

import designspace as ds
from designspace import Space
from designspace.config import flatten
from designspace.eval import Unknown, compute_activity, evaluate_arith, evaluate_bool

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


class TestRule5UnknownProvenance:
    """M10.5/D-71: Unknown has a provenance, and `.if_inactive()`
    discriminates on it — coalescing inactivity alone, never eating a
    pending (partial-eval) operand or a permanent (rule-6 emptiness) one.
    Each of the three is tested against the *other* two, per the
    conformance-law wording (API.md §Conformance Laws > Kleene)."""

    def test_coalesces_inactivity(self):
        # Already covered by TestRule1InactiveIsUnknown; repeated here so
        # all three provenances live in one place, side by side.
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        config = {"flag": False}
        activity = compute_activity(space, config)
        result = evaluate_bool(ds.param("x").if_inactive(0.0) < 5.0, config, activity, space)
        assert result is True

    def test_never_coalesces_pending(self):
        """The M10.5 headline bug: a lift that is *active* with its
        elements merely unset must stay `pending` through `.if_inactive()`
        — coalescing it would make a driver loop conclude a constraint is
        satisfied while the deciding values are still unassigned."""
        space = ds.space(
            ds.param("n").integer(1, 4),
            ds.param("bufs").integer(0, 100).repeat(ds.param("n")),
        ).require(ds.param("bufs").sum().if_inactive(0) <= 10)
        pe = space.evaluate_partial({"n": 3})
        assert pe.evaluable_constraints == ()
        assert len(pe.pending_constraints) == 1

    def test_never_coalesces_emptiness(self):
        """Rule 6: `min`/`max` of an *active* empty lift is Unknown, and
        `.if_inactive()` must not swallow it — an author wanting an empty
        lift to contribute a value writes it explicitly (API.md rule 5)."""
        space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(0))
        config = {"xs": 0}
        activity = compute_activity(space, config)
        guarded = evaluate_arith(ds.param("xs").min().if_inactive(-999.0), config, activity, space)
        assert isinstance(guarded, Unknown)


class TestRule3WhenCoercesUnknownToFalse:
    """Rule 3: `.when()` coerces Unknown to False, cascading deactivation
    along `topological_order` — a param gated on an *inactive* upstream
    param is itself inactive, not merely Unknown."""

    def test_cascading_deactivation(self):
        space = ds.space(
            ds.param("a").bool(),
            ds.param("b").real(0.0, 1.0).when(ds.param("a")),
            ds.param("c").real(0.0, 1.0).when(ds.param("b") > 0.5),
        )
        activity = compute_activity(space, {"a": False})
        assert activity["b"] is False
        assert activity["c"] is False  # cascaded from b's Unknown condition


class TestRule4ConstraintVerbsCoerceUnknownToInapplicable:
    """Rule 4: Unknown at a constraint verb is *inapplicable* — not
    violated, `margin=None`, `ConstraintEval.applicable=False`."""

    def test_inactive_operand_makes_constraint_inapplicable(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        ).require(ds.param("x") > 0.5)
        result = space.validate({"flag": False})
        (ce,) = result.constraint_evals
        assert ce.applicable is False
        assert ce.satisfied is None
        assert ce.margin is None


class TestRule7BoundCouplingsFollowRule4:
    """Rule 7: expression bounds desugar to bound-origin constraints, so an
    inactive referenced param makes the coupling inapplicable — the target
    ranges over its own envelope rather than raising."""

    def test_inactive_bound_reference_is_inapplicable(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("lo").real(0.0, 1.0).when(ds.param("flag")),
            ds.param("y").real(ds.param("lo"), 10.0),
        )
        result = space.validate({"flag": False, "y": 3.0})
        assert result.valid
        bound_evals = [ce for ce in result.constraint_evals if ce.constraint.origin == "bound"]
        assert bound_evals and all(ce.applicable is False for ce in bound_evals)


class TestRuntimeEqualityTypeTagging:
    """API.md, "Runtime equality": `==`/`!=`/`.is_in()` compare `bool` by
    type-tagged identity (`True ≠ 1` — bool is strict), `int`/`float`
    numerically (`1 == 1.0`), and every other pair by exact type match —
    deliberately distinct from Identity's declaration-time/fingerprint
    tagging, which tags uniformly. M10.5's audit: stated in the
    Expressions prose but never named in §Conformance Laws, and had no
    test at all."""

    def test_bool_is_type_tagged_against_int(self):
        space = ds.space(ds.param("x").integer(0, 10))
        activity = compute_activity(space, {"x": 1})
        assert evaluate_bool(ds.param("x") == True, {"x": 1}, activity, space) is False  # noqa: E712
        assert evaluate_bool(ds.param("x") == 1, {"x": 1}, activity, space) is True

    def test_int_and_float_compare_numerically(self):
        space = ds.space(ds.param("x").real(0.0, 10.0))
        activity = compute_activity(space, {"x": 1.0})
        assert evaluate_bool(ds.param("x") == 1, {"x": 1.0}, activity, space) is True

    def test_strings_require_exact_type_match(self):
        # A categorical may not *declare* both "1" and 1 (row 4: shared
        # string image) -- but `==`/`.is_in()` place no membership
        # requirement on the literal side (unlike row 18's ordinals), so
        # this exercises `_values_equal`'s "everything else" bucket
        # directly rather than going through a Space at all.
        from designspace.eval._kleene import _values_equal

        assert _values_equal("1", 1) is False
        assert _values_equal("1", "1") is True
        assert _values_equal("a", "a") is True
        assert _values_equal("a", "b") is False

    def test_is_in_uses_the_same_convention(self):
        space = ds.space(ds.param("x").integer(0, 10))
        activity = compute_activity(space, {"x": 1})
        assert evaluate_bool(ds.param("x").is_in(True, 2, 3), {"x": 1}, activity, space) is False
        assert evaluate_bool(ds.param("x").is_in(1, 2, 3), {"x": 1}, activity, space) is True


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

    def test_lift_element_vs_lift_element(self):
        # A regression guard for a bracket-walk bug in
        # `_resolve_param_domain` (live from M10.5 to M10.8): an ordinal
        # lift's elements, compared via *instance paths*, silently fell
        # back to raw-value comparison instead of declaration position —
        # `_ordinal_domain_of` never found the OrdinalDomain to translate
        # against, because the bracket walk computed it and then discarded
        # it (`return None` instead of `return domain`).
        space = ds.space(ds.param("g").ordinal("a", "z", "m").repeat(2))
        config = {"g": ["m", "z"]}  # declared: a=0, z=1, m=2
        flat = flatten(config, space)
        activity = compute_activity(space, flat)
        # Raw string comparison ("m" > "z") is False; declaration position
        # (index 2 > index 1) is True.
        assert evaluate_bool(ds.param("g[0]") > ds.param("g[1]"), flat, activity, space) is True

    def test_lift_element_vs_literal(self):
        space = ds.space(ds.param("g").ordinal("a", "z", "m").repeat(2))
        config = {"g": ["a", "z"]}
        flat = flatten(config, space)
        activity = compute_activity(space, flat)
        assert evaluate_bool(ds.param("g[1]") > "a", flat, activity, space) is True
        assert evaluate_bool(ds.param("g[0]") > "a", flat, activity, space) is False

    def test_chained_scalar_lift_element_vs_literal(self):
        # g[0][1] -- the other named case in _resolve_param_domain's own
        # docstring (a chained lift, two bracket levels on one segment).
        space = ds.space(
            ds.param("g").ordinal("a", "z", "m").repeat(2).repeat(1),
        )
        config = {"g": [["a", "z"]]}
        flat = flatten(config, space)
        activity = compute_activity(space, flat)
        assert evaluate_bool(ds.param("g[0][1]") > "a", flat, activity, space) is True
        assert evaluate_bool(ds.param("g[0][0]") > "a", flat, activity, space) is False


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
