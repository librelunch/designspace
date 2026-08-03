"""Conformance laws: the constraint quartet and its polarity accessors
(API.md, "Constraints and Feasibility"; PLAN.md M7.6).

Two polarity pairs — hard `forbid`/`require`, soft `encourage`/`discourage` —
read back through derived accessors so no consumer re-derives polarity from
`(origin, hard)`:

- `Constraint.kind` names the verb; `Constraint.feasible_when_satisfied` is the
  polarity (False only for the bad-state verbs forbid/discourage).
- `ConstraintEval.violated` is polarity-correct across all four kinds.
- `discourage` is the soft complement of `encourage` (== `encourage(~e)`): it
  never affects feasibility, is *flagged* iff its predicate is satisfied (the
  bad state), and — like `require` vs `forbid` — is fingerprint-equal to
  `encourage(~e)` and fingerprint-distinct from `encourage(e)` (its preimage
  canonicalizes to `Not(e)`, keeping the excluded `origin` non-load-bearing).
- A `discourage` KA vector locks the new `origin="discourage"` frozen-format
  value; all prior corpus + `require_demo` vectors stay byte-identical.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import designspace as ds
from designspace.build._space import Space

_CONF_DIR = Path(__file__).resolve().parent
if str(_CONF_DIR) not in sys.path:
    sys.path.insert(0, str(_CONF_DIR))

from _discourage_demo import build_space as build_discourage_demo  # noqa: E402

VECTORS_DIR = _CONF_DIR / "vectors"


def _one_of_each() -> dict[str, Space]:
    """A space per verb over the same params, plus a bound sugar."""

    def base() -> Space:
        return ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0))

    return {
        "forbid": base().forbid(ds.param("x") > ds.param("y")),
        "require": base().require(ds.param("x") <= ds.param("y")),
        "encourage": base().encourage(ds.param("x") <= ds.param("y")),
        "discourage": base().discourage(ds.param("x") > ds.param("y")),
        "bound": ds.space(ds.param("y").real(0.0, 1.0), ds.param("x").real(0.0, ds.param("y"))),
    }


# -- kind / feasible_when_satisfied ----------------------------------------


class TestKindAndPolarity:
    def test_kind_names_the_verb(self):
        spaces = _one_of_each()
        for verb, space in spaces.items():
            c = space.constraints[0]
            assert c.kind == verb, f"{verb!r} space produced kind {c.kind!r}"

    def test_feasible_when_satisfied_is_false_only_for_bad_state_verbs(self):
        spaces = _one_of_each()
        expected = {
            "forbid": False,
            "require": True,
            "encourage": True,
            "discourage": False,
            "bound": True,
        }
        for verb, space in spaces.items():
            assert space.constraints[0].feasible_when_satisfied is expected[verb]

    def test_hardness_matches_verb(self):
        spaces = _one_of_each()
        for verb in ("forbid", "require", "bound"):
            assert spaces[verb].constraints[0].hard is True
        for verb in ("encourage", "discourage"):
            assert spaces[verb].constraints[0].hard is False


# -- ConstraintEval.violated is polarity-correct ----------------------------


class TestViolatedPolarity:
    def test_violated_matches_each_verb_polarity(self):
        spaces = _one_of_each()
        good = {"x": 0.2, "y": 0.8}  # x <= y  (x > y is False)
        bad = {"x": 0.8, "y": 0.2}  # x > y   (x <= y is False)
        # For each verb, the config where the predicate's DESIRED value holds is
        # not violated; the other is.
        cases = {
            "forbid": (good, bad),  # good: x>y False -> ok; bad: x>y True -> violated
            "require": (good, bad),  # good: x<=y True -> ok; bad: x<=y False -> violated
            "encourage": (good, bad),
            "discourage": (good, bad),
            "bound": (good, bad),
        }
        for verb, (ok_cfg, viol_cfg) in cases.items():
            evals_ok = spaces[verb].evaluate_constraints(ok_cfg)
            evals_bad = spaces[verb].evaluate_constraints(viol_cfg)
            assert evals_ok[0].violated is False, verb
            assert evals_bad[0].violated is True, verb

    def test_is_violated_function_delegates_to_property(self):
        from designspace.eval import is_violated

        space = _one_of_each()["require"]
        ce = space.evaluate_constraints({"x": 0.8, "y": 0.2})[0]
        assert is_violated(ce) == ce.violated is True

    def test_inapplicable_is_never_violated(self):
        # Unknown predicate (inactive operand) -> inapplicable -> not violated.
        space = ds.space(
            ds.param("g").bool(),
            ds.param("z").real(0.0, 1.0).when(ds.param("g")),
        ).discourage(ds.param("z") > 0.5)
        ce = space.evaluate_constraints({"g": False})[0]
        assert ce.applicable is False
        assert ce.violated is False


# -- discourage semantics ---------------------------------------------------


class TestDiscourage:
    def _spaces(self) -> tuple[Space, Space, Space]:
        def base() -> Space:
            return ds.space(ds.param("x").real(0.0, 1.0))

        discourage = base().discourage(ds.param("x") > 0.5)
        enc_not = base().encourage(~(ds.param("x") > 0.5))
        enc_same = base().encourage(ds.param("x") > 0.5)
        return discourage, enc_not, enc_same

    def test_never_affects_feasibility(self):
        discourage, _, _ = self._spaces()
        # Even a config squarely in the discouraged state stays feasible.
        assert discourage.is_feasible({"x": 0.9}) is True
        assert discourage.is_feasible({"x": 0.1}) is True

    def test_flagged_iff_in_bad_state(self):
        discourage, _, _ = self._spaces()
        ce_bad = discourage.evaluate_constraints({"x": 0.9})[0]  # x>0.5 True (bad)
        ce_ok = discourage.evaluate_constraints({"x": 0.1})[0]  # x>0.5 False
        assert ce_bad.satisfied is True and ce_bad.violated is True
        assert ce_ok.satisfied is False and ce_ok.violated is False

    def test_fingerprint_equals_encourage_of_negation(self):
        discourage, enc_not, enc_same = self._spaces()
        assert discourage.fingerprint("full") == enc_not.fingerprint("full")
        # Distinct from the polarity-opposite spelling.
        assert discourage.fingerprint("full") != enc_same.fingerprint("full")

    def test_soft_excluded_from_sampling_scope(self):
        # Soft constraints ride only in `full`; a discourage must not change the
        # `sampling` fingerprint (it's feasibility-neutral).
        base = ds.space(ds.param("x").real(0.0, 1.0))
        with_disc = base.discourage(ds.param("x") > 0.5)
        assert base.fingerprint("sampling") == with_disc.fingerprint("sampling")
        assert base.fingerprint("full") != with_disc.fingerprint("full")

    def test_reject_soft_rejects_discouraged(self):
        discourage, _, _ = self._spaces()
        # With reject_soft, no draw should land in the discouraged state.
        for cfg in discourage.sample_dicts(200, seed=0, reject_soft=True):
            assert cfg["x"] <= 0.5


# -- Known-answer digest vector --------------------------------------------


def _load_vector() -> dict:
    path = VECTORS_DIR / "discourage_demo.json"
    if not path.exists():
        raise FileNotFoundError(
            f"missing known-answer vector {path} — generate it with "
            "`uv run python tests/conformance/vectors/_generate.py` (deliberately)"
        )
    return json.loads(path.read_text())


class TestDiscourageKnownAnswer:
    def test_fingerprint_matches_known_answer(self):
        space = build_discourage_demo()
        vector = _load_vector()
        assert space.fingerprint("full") == vector["fingerprint_full"]
        assert space.fingerprint("sampling") == vector["fingerprint_sampling"]

    def test_to_json_matches_known_answer(self):
        space = build_discourage_demo()
        vector = _load_vector()
        assert space.to_json() == vector["to_json"]
