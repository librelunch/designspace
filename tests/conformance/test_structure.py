"""Conformance laws: structure (API.md, "Parameter Types" > structural +
combinatorial; "Paths and Scoping"; "Config Utilities").

- Relocatability: a subspace behaves identically whether resolved
  standalone or nested under a choice variant / struct.
- `unflatten(flatten(c)) == c` over sampled configs (hypothesis).
- Two choices in one scope may share a variant name; variant names never
  occupy the parent scope.
- Scoping: shadowing behaves like lexical closures.
- Cascading deactivation (Kleene rule 3) through struct/choice nesting.
- Error rows introduced by M3: row 3 (subset/permutation duplicate
  items), row 5 (variant name chars; duplicate variant within one
  choice), row 17 (subset/choice weight validity), row 18 (sum_over/
  position_of/contains domain checks; M4.5 adds the ordinal
  non-member-literal comparison check to the same row).
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

import designspace as ds
from designspace.config import flatten, unflatten
from designspace.errors import ResolutionError
from designspace.eval import compute_activity


class TestRelocatability:
    """"nesting a space under a variant or struct never rewrites its
    internal references" — a subspace's own conditional-activation logic
    behaves identically whether resolved standalone or embedded."""

    @staticmethod
    def _payload():
        return ds.space(
            ds.param("flag").bool(),
            ds.param("gamma").real(0.0, 1.0).when(ds.param("flag")),
        )

    def test_standalone_and_nested_agree_on_activation(self):
        standalone = self._payload()
        nested = ds.space(ds.param("algo").choice(svm=self._payload()))

        assert standalone.validate({"flag": True, "gamma": 0.5}).valid
        assert standalone.validate({"flag": False}).valid
        assert not standalone.validate({"flag": False, "gamma": 0.5}).valid

        assert nested.validate({"algo": {"svm": {"flag": True, "gamma": 0.5}}}).valid
        assert nested.validate({"algo": {"svm": {"flag": False}}}).valid
        assert not nested.validate({"algo": {"svm": {"flag": False, "gamma": 0.5}}}).valid

    def test_two_level_nesting_composes_discriminator_conditions(self):
        """A choice nested inside a choice, nested inside a struct: the
        deepest leaf's activity must depend on *every* ancestor
        discriminator/condition, not just its immediate parent."""
        space = ds.space(
            ds.param("outer").space(
                ds.param("mode").choice(
                    "off",
                    on=ds.space(
                        ds.param("variant").choice(
                            "a",
                            b=ds.space(ds.param("depth").integer(1, 5)),
                        ),
                    ),
                ),
            ),
        )
        deep_path = "outer.mode.on.variant.b.depth"
        assert deep_path in space.params

        # Force a draw down the full "on" -> "b" chain by retrying seeds
        # until we land on it (weights are uniform, so this converges fast).
        cfg = None
        for seed in range(200):
            candidate = space.sample_one(seed=seed)
            outer = candidate.get("outer", {})
            mode = outer.get("mode")
            if isinstance(mode, dict) and "on" in mode:
                variant = mode["on"].get("variant")
                if isinstance(variant, dict) and "b" in variant:
                    cfg = candidate
                    break
        assert cfg is not None, "expected to find a full on->b draw within 200 seeds"
        assert space.validate(cfg).valid
        assert cfg["outer"]["mode"]["on"]["variant"]["b"]["depth"] in range(1, 6)

        # Turning "mode" to "off" must deactivate the entire subtree,
        # including the doubly-nested "variant.b.depth" leaf.
        activity = compute_activity(space, {"outer": {"mode": "off"}})
        assert activity["outer.mode"] is True
        assert activity[deep_path] is False
        assert space.validate({"outer": {"mode": "off"}}).valid

    def test_down_reference_from_root_forbid(self):
        """The spec's own worked example: a root-level `.forbid()`
        addressing a nested choice-variant param by full dotted path."""
        space = ds.space(
            ds.param("global_flag").bool(),
            ds.param("algo").choice(
                svm=ds.space(
                    ds.param("C").real(1e-3, 1e3),
                    ds.param("gamma").real(1e-5, 10),
                ),
            ),
        ).forbid(
            ds.param("algo.svm.C") > 100,
        )
        assert space.validate({"global_flag": True, "algo": {"svm": {"C": 50, "gamma": 1.0}}}).valid
        assert not space.validate(
            {"global_flag": True, "algo": {"svm": {"C": 500, "gamma": 1.0}}}
        ).valid


class TestUpReferenceFromEnclosingScope:
    """API.md's sole scoping rule — "resolve the first segment by walking
    up to the innermost scope where it binds" — and its worked example (a
    `.when(ds.param("global_flag"))  # up` inside a choice-variant payload).
    D-26 makes this resolve as the spec intends (D-12 previously rejected it).
    """

    @staticmethod
    def _spec_example():
        # The spec's exact example: an up-reference (`# up`) and a down-
        # reference (`# down`, the forbid) in one space, coexisting.
        return ds.space(
            ds.param("global_flag").bool(),
            ds.param("algo").choice(
                svm=ds.space(
                    ds.param("C").real(1e-3, 1e3),
                    ds.param("gamma").real(1e-5, 10).when(ds.param("global_flag")),  # up
                ),
            ),
        ).forbid(
            ds.param("algo.svm.C") > 100,  # down from root
        )

    def test_up_reference_binds_to_enclosing_param(self):
        space = self._spec_example()
        # The nested leaf's activity condition depends on the enclosing-scope
        # param plus its own discriminator — not a rewrite of either.
        condition = space.params["algo.svm.gamma"].condition
        assert condition is not None
        assert "global_flag" in condition.params

    def test_up_reference_governs_activation(self):
        space = self._spec_example()
        # global_flag True + svm selected -> gamma active (present required).
        assert space.validate(
            {"global_flag": True, "algo": {"svm": {"C": 50, "gamma": 1.0}}}
        ).valid
        # global_flag False -> gamma inactive (present is an error).
        assert space.validate({"global_flag": False, "algo": {"svm": {"C": 50}}}).valid
        assert not space.validate(
            {"global_flag": False, "algo": {"svm": {"C": 50, "gamma": 1.0}}}
        ).valid

    def test_up_and_down_references_coexist(self):
        space = self._spec_example()
        # Down-reference forbid still bites while the up-reference governs gamma.
        assert not space.validate(
            {"global_flag": True, "algo": {"svm": {"C": 500, "gamma": 1.0}}}
        ).valid

    def test_sampling_respects_up_reference(self):
        space = self._spec_example()
        saw_active = saw_inactive = False
        for seed in range(300):
            cfg = space.sample_one(seed=seed)
            algo = cfg.get("algo")
            if not (isinstance(algo, dict) and "svm" in algo):
                continue
            gamma_present = "gamma" in algo["svm"]
            assert gamma_present == cfg["global_flag"]
            saw_active |= gamma_present
            saw_inactive |= not gamma_present
        assert saw_active and saw_inactive, "expected both gamma-active and -inactive draws"


class TestFlattenUnflattenRoundTrip:
    def _space(self):
        return ds.space(
            ds.param("algo").choice(
                "linear",
                svm=ds.space(ds.param("gamma").real(1e-5, 10.0)),
            ),
            ds.param("layers").space(
                ds.param("width").integer(16, 1024),
            ),
            ds.param("ops").subset(("a", "b", "c", "d"), min_size=0, max_size=3),
            ds.param("order").permutation(("x", "y", "z")),
        )

    @given(st.integers(min_value=0, max_value=10_000))
    def test_round_trip_over_sampled_configs(self, seed):
        space = self._space()
        cfg = space.sample_one(seed=seed)
        flat = flatten(cfg, space)
        assert unflatten(flat, space) == cfg


class TestVariantNamesDoNotOccupyParentScope:
    def test_two_choices_share_a_variant_name(self):
        space = ds.space(
            ds.param("a").choice("fast", "slow"),
            ds.param("b").choice("fast", "slow"),
        )
        assert space.n_params == 2

    def test_variant_names_do_not_collide_with_sibling_param(self):
        # A variant named "fast" is scoped to its own choice, so a sibling
        # param also named "fast" at the same level is not a duplicate.
        space = ds.space(
            ds.param("algo").choice("fast", "slow"),
            ds.param("fast").bool(),
        )
        assert space.n_params == 2


class TestScopingShadowing:
    def test_inner_reference_binds_to_inner_declaration(self):
        space = ds.space(
            ds.param("x").bool(),
            ds.param("layers").space(
                ds.param("x").integer(0, 10),
                ds.param("y").integer(0, 20).when(ds.param("x") > 5),
            ),
        )
        assert space.n_params == 4  # x, layers, layers.x, layers.y
        assert space.validate({"x": True, "layers": {"x": 8, "y": 3}}).valid
        assert space.validate({"x": True, "layers": {"x": 2}}).valid
        assert not space.validate({"x": True, "layers": {"x": 2, "y": 3}}).valid


class TestCascadingDeactivation:
    def test_inactive_struct_deactivates_all_descendants(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("layers")
            .space(
                ds.param("width").integer(1, 10),
            )
            .when(ds.param("flag")),
        )
        activity = compute_activity(space, {"flag": False})
        assert activity["layers"] is False
        assert activity["layers.width"] is False

    def test_inactive_choice_deactivates_variant_payload(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("algo")
            .choice(svm=ds.space(ds.param("gamma").real(0.0, 1.0)))
            .when(ds.param("flag")),
        )
        activity = compute_activity(space, {"flag": False, "algo": "svm", "algo.svm.gamma": 0.1})
        assert activity["algo"] is False
        assert activity["algo.svm.gamma"] is False

    def test_unselected_variant_payload_is_inactive(self):
        space = ds.space(
            ds.param("algo").choice(
                "linear",
                svm=ds.space(ds.param("gamma").real(0.0, 1.0)),
            ),
        )
        activity = compute_activity(space, {"algo": "linear"})
        assert activity["algo.svm.gamma"] is False


class TestChoiceValueShapes:
    def test_bare_and_parameterized_shapes(self):
        space = ds.space(
            ds.param("algo").choice(
                "linear",
                svm=ds.space(ds.param("gamma").real(0.0, 1.0)),
            ),
        )
        for cfg in space.sample_dicts(30, seed=0):
            value = cfg["algo"]
            if value == "linear":
                assert isinstance(value, str)
            else:
                assert set(value.keys()) == {"svm"}
                assert set(value["svm"].keys()) == {"gamma"}


class TestRow3DuplicateItems:
    def test_subset_duplicate_items_raises(self):
        with pytest.raises(ResolutionError, match="'s'"):
            ds.space(ds.param("s").subset(("a", "a", "b")))

    def test_permutation_duplicate_items_raises(self):
        with pytest.raises(ResolutionError, match="'p'"):
            ds.space(ds.param("p").permutation(("a", "a", "b")))


class TestRow5VariantNames:
    def test_tuple_variant_name_with_reserved_char_raises(self):
        with pytest.raises(ResolutionError, match="path grammar"):
            ds.space(ds.param("algo").choice(("bad.name", ds.space(ds.param("x").bool()))))

    def test_bare_variant_name_with_reserved_char_raises(self):
        with pytest.raises(ResolutionError, match="path grammar"):
            ds.space(ds.param("algo").choice("bad[name]"))

    def test_duplicate_variant_name_within_one_choice_raises(self):
        with pytest.raises(ResolutionError, match="'fast'"):
            ds.space(ds.param("algo").choice("fast", "fast"))

    def test_zero_variants_raises(self):
        with pytest.raises(ResolutionError, match="at least one variant"):
            ds.space(ds.param("algo").choice())


class TestRow17SubsetChoiceWeights:
    def test_subset_weight_outside_unit_interval_raises(self):
        with pytest.raises(ResolutionError, match="'s'"):
            ds.space(ds.param("s").subset(("a", "b")).prior(weights=[1.5, 0.2]))

    def test_choice_weight_negative_raises(self):
        with pytest.raises(ResolutionError, match="'algo'"):
            ds.space(ds.param("algo").choice("a", "b").prior(weights=[1.0, -1.0]))

    def test_choice_weight_all_zero_raises(self):
        with pytest.raises(ResolutionError, match="'algo'"):
            ds.space(ds.param("algo").choice("a", "b").prior(weights=[0.0, 0.0]))

    def test_choice_weight_wrong_length_raises(self):
        with pytest.raises(ResolutionError, match="'algo'"):
            ds.space(ds.param("algo").choice("a", "b", "c").prior(weights=[1.0, 1.0]))


class TestRow18CombinatorialExpressionChecks:
    def test_sum_over_key_outside_universe_raises(self):
        with pytest.raises(ResolutionError, match="'s'"):
            ds.space(ds.param("s").subset(("a", "b"))).constrain(
                ds.param("s").sum_over({"a": 1.0, "z": 2.0}) <= 1.0
            )

    def test_position_of_non_member_raises(self):
        with pytest.raises(ResolutionError, match="'p'"):
            ds.space(ds.param("p").permutation(("a", "b"))).constrain(
                ds.param("p").position_of("z") == 0
            )

    def test_contains_on_permutation_raises(self):
        with pytest.raises(ResolutionError, match="'p'"):
            ds.space(ds.param("p").permutation(("a", "b"))).constrain(ds.param("p").contains("a"))

    def test_size_on_non_subset_raises(self):
        with pytest.raises(ResolutionError, match="'x'"):
            ds.space(ds.param("x").real(0.0, 1.0)).constrain(ds.param("x").size() > 0)

    def test_ordinal_compare_against_non_member_literal_raises(self):
        with pytest.raises(ResolutionError, match="'size'"):
            ds.space(ds.param("size").ordinal("s", "m", "l")).constrain(
                ds.param("size") > "xl"
            )

    def test_ordinal_compare_against_declared_literal_is_legal(self):
        space = ds.space(ds.param("size").ordinal("s", "m", "l")).constrain(
            ds.param("size") > "s"
        )
        assert space.n_params == 1
