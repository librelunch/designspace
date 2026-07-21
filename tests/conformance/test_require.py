"""Conformance laws: `space.require` (API.md, "Constraints and Feasibility"
> "`require` — the positive complement"; "Identity — Normalization
pipeline"; PLAN.md M7.5 gate).

`require(e)` stores the *desired (feasible)* predicate `e` and is evaluated
feasible-iff-satisfied — the same convention a bound-origin constraint uses,
`origin="require"`. The laws:

- **Fingerprint** (the strict identity law): `require(e)` is fingerprint-equal
  to `.forbid(~e)` at both scopes (its preimage canonicalizes to the
  whole-expression negation `~e` = `Not(stored_expr)`), and fingerprint-
  *distinct* from the feasibility-opposite `.forbid(e)`.
- **Semantic vs. syntactic (D-38):** `require(x<=y)` and `.forbid(x>y)` are
  *feasibility*-equal but fingerprint-*distinct* — `require` canonicalizes to
  `~(x<=y)` (`Not(Compare le)`), not the operator-flipped `x>y` that a *bound*
  sugar uses. "Equal fingerprints ⇒ equal feasible sets" is one-way, so the
  distinct fingerprint for identical feasibility is allowed.
- **Feasibility / Kleene polarity:** violated iff `e` is definitely False;
  `e` True ⇒ feasible; `e` Unknown ⇒ inapplicable (`margin is None`), feasible
  — the same `applicable`/`is_violated` as `.forbid(~e)` (only `satisfied` and
  the reported `margin` sign flip, since `require` reads in the user's terms).
- **Margin:** `require(e)` reports `margin(e)` directly (positive is slack),
  identical to a bound-origin constraint over the same predicate and the
  *negation* of `.forbid(~e)`'s reported margin (API.md L331; this is the same
  loose "margin-equal" shorthand the bound precedent uses).
- **`remaining_domain`:** a `require`-origin constraint participates in the
  one-unset-operand reduction identically to a bound.
- **KA vector:** a `require`-using space fingerprints/serializes to a committed
  byte-stable digest (the frozen format now carries `origin="require"`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import designspace as ds
from designspace.build._space import Space
from designspace.ir import RealRemaining

_CONF_DIR = Path(__file__).resolve().parent
if str(_CONF_DIR) not in sys.path:
    sys.path.insert(0, str(_CONF_DIR))

from _require_demo import build_space as build_require_demo  # noqa: E402

VECTORS_DIR = _CONF_DIR / "vectors"


def _xy() -> tuple[Space, Space, Space]:
    """`(require(x<=y), forbid(~(x<=y)), forbid(x<=y))` over the same params."""

    def base() -> Space:
        return ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0))

    require_le = base().require(ds.param("x") <= ds.param("y"))
    forbid_not = base().forbid(~(ds.param("x") <= ds.param("y")))
    forbid_le = base().forbid(ds.param("x") <= ds.param("y"))
    return require_le, forbid_not, forbid_le


# -- Fingerprint sugar-equivalence -----------------------------------------


class TestRequireFingerprint:
    def test_compare_equals_forbid_not_both_scopes(self):
        require_le, forbid_not, _ = _xy()
        assert require_le.fingerprint("full") == forbid_not.fingerprint("full")
        assert require_le.fingerprint("sampling") == forbid_not.fingerprint("sampling")

    def test_composite_equals_forbid_not(self):
        # A non-`Compare` `e` exercises the `Not`-wrap beyond op-flippable forms.
        def base() -> Space:
            return ds.space(ds.param("a").bool(), ds.param("b").bool())

        e_require = base().require(ds.param("a") & ds.param("b"))
        e_forbid = base().forbid(~(ds.param("a") & ds.param("b")))
        assert e_require.fingerprint("full") == e_forbid.fingerprint("full")
        assert e_require.fingerprint("sampling") == e_forbid.fingerprint("sampling")

    def test_distinct_from_forbid_of_same_predicate(self):
        require_le, _, forbid_le = _xy()
        assert require_le.fingerprint("full") != forbid_le.fingerprint("full")
        assert require_le.fingerprint("sampling") != forbid_le.fingerprint("sampling")

    def test_semantic_not_syntactic_vs_forbid_gt(self):
        # D-38: `require(x<=y)` and `.forbid(x>y)` are the SAME feasible set but
        # DIFFERENT fingerprints — `require` negates the whole expression
        # (`~(x<=y)` = `Not(Compare le)`), not the operator-flipped `x>y`.
        require_le, _, _ = _xy()
        forbid_gt = ds.space(
            ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0)
        ).forbid(ds.param("x") > ds.param("y"))
        for cfg in ({"x": 0.2, "y": 0.8}, {"x": 0.8, "y": 0.2}, {"x": 0.5, "y": 0.5}):
            assert require_le.is_feasible(cfg) == forbid_gt.is_feasible(cfg)
        assert require_le.fingerprint("full") != forbid_gt.fingerprint("full")


# -- Feasibility / Kleene polarity -----------------------------------------


class TestRequireFeasibility:
    def test_feasibility_matches_forbid_not(self):
        require_le, forbid_not, forbid_le = _xy()
        ok = {"x": 0.2, "y": 0.8}  # x <= y  → require satisfied → feasible
        bad = {"x": 0.8, "y": 0.2}  # x > y   → require violated  → infeasible
        for cfg, expect in ((ok, True), (bad, False)):
            assert require_le.is_feasible(cfg) is expect
            assert forbid_not.is_feasible(cfg) is expect
            assert forbid_le.is_feasible(cfg) is not expect

    def test_infeasibility_reasons_names_violation(self):
        require_le, _, _ = _xy()
        reasons = require_le.infeasibility_reasons({"x": 0.8, "y": 0.2})
        assert reasons  # a require violation is reported

    def test_kleene_true_false_unknown(self):
        # `g` gates `z`; when `g` is False, `z` is inactive and `z > 0.5` is
        # Unknown — require then inapplicable (margin None), config feasible.
        def base() -> Space:
            return ds.space(
                ds.param("g").bool(),
                ds.param("z").real(0.0, 1.0).when(ds.param("g")),
            )

        require_z = base().require(ds.param("z") > 0.5)
        forbid_z = base().forbid(~(ds.param("z") > 0.5))

        true_cfg = {"g": True, "z": 0.8}  # e True  → feasible
        false_cfg = {"g": True, "z": 0.2}  # e False → infeasible
        unknown_cfg = {"g": False}  # e Unknown → inapplicable, feasible

        assert require_z.is_feasible(true_cfg) is True
        assert require_z.is_feasible(false_cfg) is False
        assert require_z.is_feasible(unknown_cfg) is True

        # `applicable` matches `.forbid(~e)` exactly (only `satisfied`/`margin`
        # sign flip). The Unknown case is inapplicable with margin None.
        for cfg in (true_cfg, false_cfg, unknown_cfg):
            r_ce = require_z.evaluate_constraints(cfg)[0]
            f_ce = forbid_z.evaluate_constraints(cfg)[0]
            assert r_ce.applicable == f_ce.applicable
        u_ce = require_z.evaluate_constraints(unknown_cfg)[0]
        assert u_ce.applicable is False
        assert u_ce.satisfied is None
        assert u_ce.margin is None


# -- Margin -----------------------------------------------------------------


class TestRequireMargin:
    def test_reports_feasible_predicate_margin(self):
        # `require(x<=y)` reports `margin(x<=y) = y - x` (positive is slack),
        # identical to a bound-origin constraint over the same predicate and
        # the negation of `.forbid(~e)`'s reported margin.
        require_le, forbid_not, _ = _xy()
        bound = ds.space(
            ds.param("y").real(0.0, 1.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        cfg = {"x": 0.2, "y": 0.8}
        r_margin = require_le.evaluate_constraints(cfg)[0].margin
        b_margin = bound.evaluate_constraints(cfg)[0].margin
        f_margin = forbid_not.evaluate_constraints(cfg)[0].margin
        assert f_margin is not None
        assert r_margin == pytest.approx(0.6)  # y - x, positive slack
        assert r_margin == pytest.approx(b_margin)
        assert r_margin == pytest.approx(-f_margin)


# -- Sampler rejects on requires -------------------------------------------


class TestRequireSampling:
    def test_sampler_only_draws_satisfying_configs(self):
        require_le, _, _ = _xy()
        for cfg in require_le.sample_dicts(200, seed=0):
            assert cfg["x"] <= cfg["y"]


# -- remaining_domain participation ----------------------------------------


class TestRequireRemainingDomain:
    def test_require_narrows_like_a_bound(self):
        # With `y` set, `require(x <= y)` narrows `x`'s remaining upper bound to
        # `y` — the same one-unset-operand reduction a bound performs.
        require_le, _, _ = _xy()
        rd = require_le.remaining_domain("x", {"y": 0.4})
        assert isinstance(rd, RealRemaining)
        assert rd.hi == pytest.approx(0.4)
        assert rd.lo == pytest.approx(0.0)

    def test_sound_never_excludes_feasible(self):
        # A still-feasible value survives the reduction.
        require_le, _, _ = _xy()
        rd = require_le.remaining_domain("x", {"y": 0.4})
        assert isinstance(rd, RealRemaining) and rd.lo <= 0.3 <= rd.hi

    def test_misuse_typeerror_on_empty_and_missing_path(self):
        require_le, _, _ = _xy()
        with pytest.raises(TypeError):
            require_le.remaining_domain("", {})
        with pytest.raises(TypeError):
            require_le.remaining_domain("nonesuch", {})


# -- Known-answer digest vector --------------------------------------------


def _load_vector() -> dict:
    path = VECTORS_DIR / "require_demo.json"
    if not path.exists():
        raise FileNotFoundError(
            f"missing known-answer vector {path} — generate it with "
            "`uv run python tests/conformance/vectors/_generate.py` "
            "(deliberately; never auto-generated)"
        )
    return json.loads(path.read_text())


class TestRequireKnownAnswer:
    def test_fingerprint_matches_known_answer(self):
        space = build_require_demo()
        vector = _load_vector()
        assert space.fingerprint("full") == vector["fingerprint_full"]
        assert space.fingerprint("sampling") == vector["fingerprint_sampling"]

    def test_to_json_matches_known_answer(self):
        space = build_require_demo()
        vector = _load_vector()
        assert space.to_json() == vector["to_json"]
