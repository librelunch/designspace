"""Conformance laws: Identity and Serialization (API.md, "Identity and
Serialization"; "Conformance Laws" > "Identity").

- Sugar-equivalence pairs fingerprint-equal.
- Bound-origin polarity (D-29(4)): fingerprint- and feasibility-equal to the
  `.forbid(x > y)` manual expansion; fingerprint- and feasibility-*distinct*
  from the feasibility-opposite `.forbid(x <= y)`.
- Order-sensitivity: permuted declarations differ; `.when(a).when(b)` folds
  in call order.
- Scope monotonicity: meta/tags/declared-constraint changes are
  `sampling`-equal, `full`-distinct (DECISIONS.md D-33: `quantized`/
  `periodic` ride in *both* scopes despite the table's "domain, prior" row).
- Round-trip law.
- Mark-sentinel distinctness; type-tag distinctness; float edges.
- `config_hash`/`config_diff` laws.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace import Space


class _FakePrior:
    """A minimal external `Prior` (ppf-only): opaque for identity purposes
    (DECISIONS.md D-31) — no structural encoding."""

    def ppf(self, q: float) -> float:
        return q


# -- Sugar-equivalence -----------------------------------------------------


class TestSugarEquivalence:
    def test_log_scale_equals_explicit_log_prior(self):
        a = ds.space(ds.param("x").real(1e-5, 1.0).log_scale())
        b = ds.space(ds.param("x").real(1e-5, 1.0).prior(ds.Log()))
        assert a.fingerprint() == b.fingerprint()

    def test_implies_equals_not_or(self):
        def make(build_forbid):
            return ds.space(ds.param("x").real(0, 1), ds.param("y").real(0, 1)).forbid(
                build_forbid()
            )

        a = make(lambda: (ds.param("x") > 0.5).implies(ds.param("y") > 0.5))
        b = make(lambda: ~(ds.param("x") > 0.5) | (ds.param("y") > 0.5))
        assert a.fingerprint() == b.fingerprint()

    def test_variadic_repeat_equals_chain(self):
        a = ds.space(ds.param("grid").real(0, 1).repeat(2, 3))
        b = ds.space(ds.param("grid").real(0, 1).repeat(3).repeat(2))
        assert a.fingerprint() == b.fingerprint()

    def test_expression_bound_equals_forbid_manual_expansion(self):
        lo, hi = 4096, 65536
        sugared = ds.space(
            ds.param("total").integer(lo, hi), ds.param("buf").integer(1, ds.param("total"))
        )
        manual = ds.space(ds.param("total").integer(lo, hi), ds.param("buf").integer(1, hi)).forbid(
            ds.param("buf") > ds.param("total")
        )
        assert sugared.fingerprint() == manual.fingerprint()


# -- Bound-origin polarity (D-29(4)) ---------------------------------------


class TestBoundOriginPolarity:
    def _spaces(self) -> tuple[Space, Space, Space]:
        lo, hi = 4096, 65536
        sugared = ds.space(
            ds.param("total").integer(lo, hi), ds.param("buf").integer(1, ds.param("total"))
        )
        forbid_gt = ds.space(
            ds.param("total").integer(lo, hi), ds.param("buf").integer(1, hi)
        ).forbid(ds.param("buf") > ds.param("total"))
        forbid_le = ds.space(
            ds.param("total").integer(lo, hi), ds.param("buf").integer(1, hi)
        ).forbid(ds.param("buf") <= ds.param("total"))
        return sugared, forbid_gt, forbid_le

    def test_fingerprint_equal_to_forbid_gt(self):
        sugared, forbid_gt, _ = self._spaces()
        assert sugared.fingerprint() == forbid_gt.fingerprint()
        assert sugared.fingerprint("sampling") == forbid_gt.fingerprint("sampling")

    def test_fingerprint_distinct_from_forbid_le(self):
        sugared, _, forbid_le = self._spaces()
        assert sugared.fingerprint() != forbid_le.fingerprint()

    def test_feasibility_matches_forbid_gt_not_forbid_le(self):
        sugared, forbid_gt, forbid_le = self._spaces()
        ok = {"total": 5000, "buf": 3000}  # buf <= total
        bad = {"total": 5000, "buf": 6000}  # buf > total
        for cfg, expect in ((ok, True), (bad, False)):
            assert sugared.is_feasible(cfg) is expect
            assert forbid_gt.is_feasible(cfg) is expect
            assert forbid_le.is_feasible(cfg) is not expect


# -- Order-sensitivity -------------------------------------------------


class TestOrderSensitivity:
    def test_permuted_params_differ(self):
        a = ds.space(ds.param("x").real(0, 1), ds.param("y").real(0, 1))
        b = ds.space(ds.param("y").real(0, 1), ds.param("x").real(0, 1))
        assert a.fingerprint() != b.fingerprint()

    def test_permuted_choice_variants_differ(self):
        a = ds.space(ds.param("c").choice("first", "second"))
        b = ds.space(ds.param("c").choice("second", "first"))
        assert a.fingerprint() != b.fingerprint()

    def test_when_call_order_is_preserved(self):
        # `.when(a).when(b)` ANDs left-to-right; the operand order this
        # produces is itself what "call order" means — swapping the calls
        # swaps `BoolOp.children` order, which the AST codec preserves.
        cond_a = ds.param("t").real(0, 1) > 0.5
        cond_b = ds.param("u").bool()

        def make(first, second):
            return ds.space(
                ds.param("t").real(0, 1),
                ds.param("u").bool(),
                ds.param("x").real(0, 1).when(first).when(second),
            )

        ab = make(cond_a, cond_b)
        ba = make(cond_b, cond_a)
        assert ab.fingerprint() != ba.fingerprint()


# -- Scope monotonicity -----------------------------------------------


class TestScopeMonotonicity:
    def test_tag_change_is_sampling_equal_full_distinct(self):
        a = ds.space(ds.param("x").real(0, 1).tag("a"))
        b = ds.space(ds.param("x").real(0, 1).tag("b"))
        assert a.fingerprint("sampling") == b.fingerprint("sampling")
        assert a.fingerprint("full") != b.fingerprint("full")

    def test_meta_change_is_sampling_equal_full_distinct(self):
        a = ds.space(ds.param("x").real(0, 1).meta(note="a"))
        b = ds.space(ds.param("x").real(0, 1).meta(note="b"))
        assert a.fingerprint("sampling") == b.fingerprint("sampling")
        assert a.fingerprint("full") != b.fingerprint("full")

    def test_default_change_is_sampling_equal_full_distinct(self):
        a = ds.space(ds.param("x").real(0, 1).default(0.1))
        b = ds.space(ds.param("x").real(0, 1).default(0.2))
        assert a.fingerprint("sampling") == b.fingerprint("sampling")
        assert a.fingerprint("full") != b.fingerprint("full")

    def test_declared_constraint_is_sampling_equal_full_distinct(self):
        base = ds.space(ds.param("x").real(0, 1))
        a = base
        b = base.encourage(ds.param("x") > 0.9)
        assert a.fingerprint("sampling") == b.fingerprint("sampling")
        assert a.fingerprint("full") != b.fingerprint("full")

    def test_hard_forbid_differs_at_both_scopes(self):
        base = ds.space(ds.param("x").real(0, 1))
        a = base
        b = base.forbid(ds.param("x") > 0.9)
        assert a.fingerprint("sampling") != b.fingerprint("sampling")
        assert a.fingerprint("full") != b.fingerprint("full")

    def test_quantized_change_differs_at_both_scopes(self):
        # DECISIONS.md D-33: chart geometry (quantized/periodic) rides in
        # both scopes despite the scope table's "domain, prior" shorthand.
        a = ds.space(ds.param("x").real(0.0, 1.0))
        b = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1))
        assert a.fingerprint("full") != b.fingerprint("full")
        assert a.fingerprint("sampling") != b.fingerprint("sampling")

    def test_periodic_change_differs_at_both_scopes(self):
        a = ds.space(ds.param("angle").real(0.0, 360.0))
        b = ds.space(ds.param("angle").real(0.0, 360.0, periodic=True))
        assert a.fingerprint("full") != b.fingerprint("full")
        assert a.fingerprint("sampling") != b.fingerprint("sampling")


# -- Round-trip -------------------------------------------------------


class TestRoundTrip:
    def _spaces(self) -> list[Space]:
        return [
            ds.space(
                ds.param("lr").real(1e-5, 1.0).log_scale(),
                ds.param("n").integer(1, 10).quantized(step=2),
                ds.param("c").categorical(1, 2, "x"),
                ds.param("o").ordinal("lo", "mid", "hi"),
                ds.param("b").bool(),
                ds.param("s").subset(["a", "b", "c"], min_size=1),
                ds.param("p").permutation(["a", "b", "c"]),
                ds.param("choice").choice("off", on=ds.space(ds.param("level").real(0, 1))),
                ds.param("group").space(ds.param("inner").real(0, 1), ds.param("flag").bool()),
                ds.param("lifted").real(0, 1).default(0.5).repeat(3),
            )
            .forbid(ds.param("lr") < 1e-4)
            .encourage(ds.param("n") > 1, tags=("soft",), meta={"note": "x"})
        ]

    def test_fingerprint_round_trips_at_both_scopes(self):
        for space in self._spaces():
            doc = space.to_json()
            restored = Space.from_json(doc)
            assert restored.fingerprint() == space.fingerprint()
            assert restored.fingerprint("sampling") == space.fingerprint("sampling")

    def test_to_json_round_trips(self):
        for space in self._spaces():
            doc = space.to_json()
            restored = Space.from_json(doc)
            assert restored.to_json() == doc

    def test_round_tripped_space_samples_and_validates(self):
        for space in self._spaces():
            restored = Space.from_json(space.to_json())
            for cfg in restored.sample_dicts(20, seed=0):
                assert restored.validate(cfg).valid


# -- Nested (list/dict-shaped) meta values (DECISIONS.md D-36) -------------


class TestNestedMetaValues:
    def test_param_meta_list_and_dict_round_trip(self):
        space = ds.space(
            ds.param("x").real(0, 1).meta(tags_list=[1, "two", 3.0], nested={"a": [True, None]})
        )
        restored = Space.from_json(space.to_json())
        assert dict(restored.params["x"].meta) == dict(space.params["x"].meta)
        assert restored.fingerprint() == space.fingerprint()

    def test_constraint_meta_list_and_dict_round_trip(self):
        space = ds.space(ds.param("x").real(0, 1)).encourage(
            ds.param("x") > 0.5, meta={"history": [{"step": 1}, {"step": 2}]}
        )
        restored = Space.from_json(space.to_json())
        assert dict(restored.constraints[0].meta) == dict(space.constraints[0].meta)
        assert restored.fingerprint() == space.fingerprint()

    def test_nested_meta_is_type_tag_distinct(self):
        a = ds.space(ds.param("x").real(0, 1).meta(k=[1, 2]))
        b = ds.space(ds.param("x").real(0, 1).meta(k=[1.0, 2.0]))
        assert a.fingerprint() != b.fingerprint()


# -- Mark-sentinel / type-tag / float-edge distinctness --------------------


class TestMarkSentinelDistinctness:
    def test_opaque_prior_raises_by_default(self):
        space = ds.space(ds.param("x").real(0, 1).prior(_FakePrior()))
        with pytest.raises(ds.SerializationError):
            space.fingerprint()

    def test_mark_produces_distinct_fingerprint_from_no_prior(self):
        marked = ds.space(ds.param("x").real(0, 1).prior(_FakePrior()))
        uniform = ds.space(ds.param("x").real(0, 1))
        assert marked.fingerprint(on_unserializable="mark") != uniform.fingerprint()

    def test_to_json_drop_manifests_and_differs_from_uniform(self):
        marked = ds.space(ds.param("x").real(0, 1).prior(_FakePrior()))
        doc = marked.to_json(on_unserializable="drop")
        assert doc["dropped"]
        assert "prior" not in doc["params"][0]


class TestTypeTagDistinctness:
    def test_categorical_int_vs_float(self):
        a = ds.space(ds.param("c").categorical(1, 2))
        b = ds.space(ds.param("c").categorical(1.0, 2.0))
        assert a.fingerprint() != b.fingerprint()

    def test_categorical_bool_vs_int(self):
        a = ds.space(ds.param("c").categorical(True, False))
        b = ds.space(ds.param("c").categorical(1, 0))
        assert a.fingerprint() != b.fingerprint()

    def test_config_hash_distinguishes_int_and_float(self):
        space = ds.space(ds.param("c").categorical(1, 1.0))
        h_int = ds.config_hash({"c": 1}, space)
        h_float = ds.config_hash({"c": 1.0}, space)
        assert h_int != h_float


class TestFloatEdges:
    def test_negative_zero_bound_equals_positive_zero(self):
        a = ds.space(ds.param("x").real(-0.0, 1.0))
        b = ds.space(ds.param("x").real(0.0, 1.0))
        assert a.fingerprint() == b.fingerprint()

    def test_negative_zero_default_equals_positive_zero(self):
        a = ds.space(ds.param("x").real(-1.0, 1.0).default(-0.0))
        b = ds.space(ds.param("x").real(-1.0, 1.0).default(0.0))
        assert a.fingerprint() == b.fingerprint()

    def test_negative_zero_config_hash_equals_positive_zero(self):
        space = ds.space(ds.param("x").real(-1.0, 1.0))
        assert ds.config_hash({"x": -0.0}, space) == ds.config_hash({"x": 0.0}, space)


# -- Format version -----------------------------------------------------


class TestFormatVersion:
    def test_unknown_version_raises_on_from_json(self):
        space = ds.space(ds.param("x").real(0, 1))
        doc = dict(space.to_json())
        doc["version"] = 999
        with pytest.raises(ds.SerializationError):
            Space.from_json(doc)

    def test_fingerprint_prefix_names_version_and_scope(self):
        space = ds.space(ds.param("x").real(0, 1))
        fp = space.fingerprint(scope="sampling")
        version, scope, digest = fp.split(":")
        assert version == "1"
        assert scope == "sampling"
        assert len(digest) == 64


# -- config_hash / config_diff -------------------------------------------


class TestConfigHash:
    def test_subset_order_independent(self):
        space = ds.space(ds.param("s").subset(["a", "b", "c"], min_size=0))
        assert ds.config_hash({"s": ["a", "b"]}, space) == ds.config_hash({"s": ["b", "a"]}, space)

    def test_permutation_order_dependent(self):
        space = ds.space(ds.param("p").permutation(["a", "b", "c"]))
        assert ds.config_hash({"p": ["a", "b", "c"]}, space) != ds.config_hash(
            {"p": ["c", "b", "a"]}, space
        )

    def test_quantized_grid_canonicalizes(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1))
        # 0.30000000000000004 and 0.3 both round to the same grid point.
        assert ds.config_hash({"x": 0.1 + 0.1 + 0.1}, space) == ds.config_hash({"x": 0.3}, space)

    def test_does_not_embed_space_fingerprint(self):
        space_a = ds.space(ds.param("x").real(0, 1))
        space_b = ds.space(ds.param("x").real(0, 1).tag("unrelated"))
        assert space_a.fingerprint() != space_b.fingerprint()
        assert ds.config_hash({"x": 0.5}, space_a) == ds.config_hash({"x": 0.5}, space_b)


class TestConfigDiff:
    def test_variant_switch_decomposes(self):
        space = ds.space(ds.param("opt").choice("sgd", adam=ds.space(ds.param("beta1").real(0, 1))))
        a = {"opt": {"adam": {"beta1": 0.9}}}
        b = {"opt": "sgd"}
        diffs = {d.param: d for d in ds.config_diff(a, b, space)}
        assert diffs["opt"].old == "adam" and diffs["opt"].new == "sgd"
        assert diffs["opt.adam.beta1"].old == 0.9 and diffs["opt.adam.beta1"].new is None

    def test_repeat_length_change_aligns_positionally(self):
        space = ds.space(
            ds.param("n").integer(0, 5), ds.param("xs").real(0, 1).repeat(ds.param("n"))
        )
        a = {"n": 2, "xs": [0.1, 0.2]}
        b = {"n": 3, "xs": [0.9, 0.1, 0.2]}  # insertion at front -> full rewrite
        diffs = {d.param: d for d in ds.config_diff(a, b, space)}
        assert diffs["xs"].old == 2 and diffs["xs"].new == 3
        assert diffs["xs[0]"].old == 0.1 and diffs["xs[0]"].new == 0.9
        assert diffs["xs[1]"].old == 0.2 and diffs["xs[1]"].new == 0.1
        assert diffs["xs[2]"].old is None and diffs["xs[2]"].new == 0.2

    def test_no_change_yields_empty_diff(self):
        space = ds.space(ds.param("x").real(0, 1))
        cfg = {"x": 0.5}
        assert ds.config_diff(cfg, dict(cfg), space) == []

    def test_int_and_float_equal_value_yields_empty_diff(self):
        # DECISIONS.md D-35: config_diff uses plain Python equality (1 == 1.0),
        # unlike config_hash/fingerprint's type-tagged distinctness.
        space = ds.space(ds.param("c").categorical(1, 1.0))
        assert ds.config_diff({"c": 1}, {"c": 1.0}, space) == []
